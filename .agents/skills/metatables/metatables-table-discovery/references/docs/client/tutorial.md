# Tutorial: prices, returns, volatility, and execution roots

Build a small data pipeline with the MetaTables Python client. You will define
an instrument table and three time-index tables, load recorded prices, calculate
daily returns and rolling volatility, and read published results independently.
Choose different execution roots and inspect successes and simulated failures.

The complete code is in [src/metatables/examples/tutorial](../examples/tutorial/README.md).
Run commands from the MetaTables repository root in the Python environment where
[MetaTables and the compatible SDK](installation-and-connection.md) are installed.
The sample contains recorded SPY, QQQ, and IWM prices; a symbol is simply the key
identifying one instrument. No market-data service is needed for this exercise.

## 1. Preview the data

```bash
python -m metatables.examples.tutorial preview
```

This command needs no API connection. Expect `Recorded prices: 69 rows` and
`Daily returns: 66 rows`, and `Rolling volatility (5 sessions): 54 rows`, followed
by the final volatility observations. There are 23 trading
dates per symbol. A return needs a preceding price, so each symbol has 22 returns.

[frames.py](../examples/tutorial/frames.py) loads the unchanged
[recorded CSV](../examples/tutorial/data/yahoo_spy_qqq_iwm_2026-06-15_2026-07-17.csv)
and calculates each symbol's change independently:

```python
from metatables.examples.tutorial.frames import daily_returns, recorded_prices, rolling_volatility

prices = recorded_prices()
returns = daily_returns(prices)
volatility = rolling_volatility(returns)
print(volatility.head())
```

A daily return is `current_adjusted_close / previous_adjusted_close - 1`.
A value of `0.01` represents a 1% change. The first observation has no return.
The sample is finite: rerunning it does not fetch newer market observations.
Volatility uses each symbol's last five trading-session returns: sample standard
deviation (`ddof=1`) multiplied by `sqrt(252)`. The first four returns lack a full
window, leaving 18 volatility observations per symbol.

## 2. Understand the contracts

Read [tables.py](../examples/tutorial/tables.py):

| Model | One row represents | Meaning |
| --- | --- | --- |
| `Asset` | One symbol | A stable instrument UID, ticker, and display name. |
| `DailyClose` | One UTC trading day + symbol | A recorded adjusted closing price. |
| `DailyReturn` | One UTC trading day + symbol | A change calculated from successive prices. |
| `RollingVolatility` | One UTC trading day + symbol | Annualized volatility over a trailing return window. |

`Asset` extends `PlatformManagedMetaTable`. The three observation tables extend
`PlatformTimeIndexMetaTable` and declare `__index_names__ = ["time_index", "symbol"]`.
This coordinate is their row grain. Their SQLAlchemy foreign keys reference the
unique `Asset.symbol`, and the time-index mixin creates a unique index over the
full grain. Their `1d` cadence describes daily observations; it does not promise
rows on weekends or holidays.

All four have descriptions, documented columns, explicit physical names, and
logical identifiers under `metatables_market_tutorial`. A logical identifier
finds a catalog resource; the catalog UID authorizes requests; the physical table
name identifies database storage. These are distinct values.

The in-memory frames use the same grain as a pandas MultiIndex, with `time_index`
first and dtype `datetime64[ns, UTC]`. `adjusted_close`, `daily_return`, and `annualized_volatility` are
payload columns, not index dimensions.

## 3. Application schema prerequisite

Start the [local API](../operations/local-runtime.md) from this checkout, and use
the same API URL, private local token, and SDK login in the tutorial shell. SQLite
stores both catalog and rows; an unregistered branch such as `test` works. A
hosted API uses the same commands with its configured source and permissions.

```bash
export METATABLES_API_URL=http://127.0.0.1:18473
```

In Settings, check the runtime DataSource and explicitly choose **Run MetaTables
migrations**, or select an already initialized database. Startup does not migrate;
a hosted API's deployment applies these before it rolls out.
These are system migrations only. The tutorial's application migrations run
in the application's Python process through the client in both modes:

```bash
python -m metatables.examples.scripts.setup_metatables --development-client ~/.local/share/metatables/server.json
```

Omit `--development-client` to use hosted deployment discovery. The application
process loads `metatables.examples.tutorial.migrations:migration` and uses the selected
runtime's environment connection. The API needs no tutorial provider installation
or configuration. The script reserves missing catalog bindings, applies outstanding
Alembic revisions locally, and finalizes tables. It does not seed rows or run producers.

The [provider](../examples/tutorial/migrations/__init__.py),
[registry](../examples/tutorial/migrations/registry.py), and
[initial revision](../examples/tutorial/migrations/versions/metatables_market_tutorial/0001_create_market_tutorial_tables.py)
are the reviewed code executed by the client. Review them alongside
[the migration boundary](define-and-migrate-tables.md). Every `seed`, `update`, and
`read` command runs migration setup first, requiring Writer access to each existing
provider table. VS Code launches also use `--prepare-data` to seed and run producers
before reading. An independent `TimeIndexTableRef` reader needs Reader access only
and does not run setup. Preview works immediately without an API.

The additive [volatility revision](../examples/tutorial/migrations/versions/metatables_market_tutorial/0002_create_rolling_volatility.py)
upgrades `0001` to `0002`. It creates only the new volatility table and its index;
existing rows and catalog identities are retained. Restart an API running older
tutorial code so it loads the updated provider before setup.

## 4. Seed the instrument table

```bash
python -m metatables.examples.tutorial seed
```

Expect the three instrument rows. [operations.py](../examples/tutorial/operations.py)
resolves the `Asset` catalog resource, compiles a SQLAlchemy insert for the API-advertised dialect with
bound values, and declares write access to that table's UID. Its physical target
comes from the returned resource. Repeating the command updates display names and
preserves instrument identity without inserting duplicate symbols.

Seed first because the three time-index tables' foreign keys require those symbols.

## 5. Run the connected updaters

```bash
python -m metatables.examples.tutorial update --root returns
python -m metatables.examples.tutorial update --root volatility
```

[updaters.py](../examples/tutorial/updaters.py) contains three producers:

1. `RecordedPrices` loads fixture prices newer than its last stored observation.
2. `DailyReturns` declares the price producer in `dependencies()`, reads its
   published table, calculates per-symbol returns, and emits only new results.
3. `RollingVolatility` declares `DailyReturns` in `dependencies()`, reads its
   published return table, and emits new observations with complete rolling windows.

The example calls only the selected root's `run()`. The library executes its
declared dependencies; the example never separately runs them or sets run states.
The same configured `DailyReturns` producer is a root with `--root returns` and a
dependency with `--root volatility`. All constructors use
explicit `config` and `output_table` values. The tables must already be migrated;
the client resolves their active bindings when constructing a producer in a new
process. An unbound or inaccessible table is an error, not permission to create it.

Configuration fields participate in update identity. The return producer's
`price_table` field identifies its upstream storage. Volatility also configures its
return table and rolling window (five trading sessions by default). The example's
`hash_namespace="market-tutorial"` separates producer identities; it does **not**
create separate output tables. Use the dedicated tutorial tables for this exercise.

On success, expect `"completed": true`, the chosen root class, and an update hash.
A fresh returns invocation writes 69 prices and 66 returns. A successful volatility
invocation also writes 54 volatility observations. Repeating either against the
completed sample emits no newer observations.
The return calculation reads this small sample's full price history before
filtering new output, so it retains the preceding price at the incremental
boundary. Large datasets should read only the history needed for their calculation.
Volatility likewise retains the preceding return window before filtering new output.

### Simulated failures and root choices

`DailyReturns.update()` draws once per attempt and raises a clearly labelled
simulated error with **50% probability**, before reading prices or writing returns.
The draw happens even when there are no new observations. It is execution behavior,
not a configuration field that creates another producer identity. Pure preview
calculations remain deterministic. A short batch need not have exactly half failures.

| Selected root | Library execution order | If DailyReturns fails |
| --- | --- | --- |
| `DailyReturns` | Prices → Returns | Returns fails and its root invocation fails. |
| `RollingVolatility` | Prices → Returns → Volatility | Returns fails; volatility is blocked before calculation and its root invocation fails. |

Inspect the saved invocation graph and exact attempt logs in **Runs**. The library
records these outcomes through its usual lifecycle. Failure preserves previously
published output and adds another historical invocation.

The four VS Code example launches choose Local API or Hosted deployment and one
of these roots. Each uses `read --prepare-data --root ...`: migrate, seed, invoke
the chosen root once, then read its output on success. The Debug Console opens
immediately and shows the API target and selected root. A simulated error stops
that launch after the library records the failed run. Re-run either launch to
generate additional history. Using `update --prepare-data` also invokes its root
only once.

## 6. Read the result independently

```bash
python -m metatables.examples.tutorial read --root returns --symbol SPY
python -m metatables.examples.tutorial read --root volatility --symbol SPY
```

The reader resolves the published table by logical identifier and selects one
symbol. Without `--prepare-data`, it does not construct or execute an updater:

```python
from metatables import TimeIndexTableRef
from metatables.examples.tutorial.tables import RETURN_IDENTIFIER

reference = TimeIndexTableRef.from_identifier(RETURN_IDENTIFIER)
frame = reference.get_df_between_dates(
    start_date="2026-06-15T00:00:00Z",
    dimension_filters={"symbol": ["SPY"]},
    columns=["daily_return"],
)
```

On the complete sample, SPY has 22 return rows ending July 17. The command displays
the last six. The volatility reader selects `VOLATILITY_IDENTIFIER` and
`annualized_volatility`, yielding 18 rows for SPY. The caller still needs view access even though the reader does not
know how to produce the data.

## Verify or adapt the example

```bash
python -m pytest -q tests/examples/test_tutorial.py -k 'not postgresql'
python -m pytest -q 'tests/e2e/test_sqlite_runtime.py::test_tutorial_selected_roots_use_library_dependency_execution_and_failure_states[sqlite]'
```

The focused tests check per-symbol calculations, incremental boundaries, UTC
precision, shared producer identity, the failure threshold, and an additive upgrade
from `0001` on temporary SQLite. The API test exercises real loopback HTTP,
application-owned migrations, both roots, and controlled random draws for success
and failure. It verifies library-recorded graphs, blocked volatility, and retained
run history. SDK identity is stubbed; platform physical credentials and PostgreSQL
connections are forbidden. Container/engine-matrix testing is separate and only
runs on explicit demand; see the [testing guide](../contributing/testing.md).

To build your own pipeline, keep the same contract → migration → seed → producer
→ reader workflow. Replace the recorded-data loader with your data source and
choose your own physical names, identifiers, grain, and configuration.
