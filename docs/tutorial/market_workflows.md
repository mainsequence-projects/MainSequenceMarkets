# Market Workflows

These examples show the intended runtime boundary.

1. Use typed `msm.api` row APIs for market records.
2. Initialize the required MetaTable runtime explicitly during process startup.
3. Treat row operations as business operations only; they do not register or
   attach MetaTables on first use.
4. Use DataNode helpers for historical tables such as holdings and target
   positions.

## Runtime Setup

Production code normally initializes the required market MetaTables during
application startup. A row call such as `Asset.upsert(...)` uses the active
runtime and then runs the operation. If the runtime is missing, or if the
runtime was initialized without the required table set, the error tells the
caller to run explicit preflight.

Explicit preflight remains available for applications that want startup-time
registration or verification:

```python
import msm

runtime = msm.start_engine(models=["Asset"])
```

Schema creation does not take labels. Use `runtime.meta_tables`,
`runtime.meta_table_models`, and `runtime.data_nodes` after bootstrap when a
specific returned resource needs follow-up labeling or handling. The preflight
uses the Main Sequence logger at `info` level to report each MetaTable model
being registered, what context was created, and when a cached runtime is reused.

For externally managed tables, create/migrate the tables in application code and
use the explicit startup/bootstrap path with `management_mode="external_registered"`.
Direct `register_markets_meta_tables(...)` calls are lower-level maintenance or
migration plumbing, not the normal application workflow.

Examples that use the platform namespace `mainsequence.examples` set
`MSM_AUTO_REGISTER_NAMESPACE` before importing `msm.api`, then call
`msm.start_engine(...)` before row operations:

```python
import os

from examples.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm

msm.start_engine(models=["Asset"])
```

The returned runtime from explicit preflight still exposes table handles and
context for lower-level repository/service internals, but examples should not
pass those handles around for normal row CRUD.

## Assets And Categories

Start with assets before building reusable universes. Asset identity is the
stable contract consumed by holdings, target positions, pricing details, and
portfolio workflows.

```python
from msm.api.assets import Asset
from msm.constants import ASSET_TYPE_CRYPTO

btc = Asset.upsert(
    unique_identifier="example-asset-btc",
    asset_type=ASSET_TYPE_CRYPTO,
)

btc_by_identifier = Asset.get_by_unique_identifier(
    unique_identifier="example-asset-btc",
)
btc_by_uid = Asset.get_by_uid(btc.uid)
crypto_assets = Asset.filter(
    unique_identifier_contains="example-asset-",
    asset_type=ASSET_TYPE_CRYPTO,
    limit=20,
)
# Optional cleanup for temporary custom assets only:
# Asset.delete(btc.uid)
```

Do not delete assets during normal setup. Use cleanup only for temporary or
organization-owned custom assets. Shared public/mastered assets should remain
stable so downstream workflows do not lose their canonical identity.

See `examples/msm/assets/asset_crud_workflow.py` for the focused workflow. It uses
explicit example-namespace bootstrap for the required `AssetType`, `Asset`, and
`OpenFigiDetails` MetaTables, creates temporary custom assets, resolves
`BBG00FNFPQH4` through OpenFIGI, writes an AssetSnapshot frame from the returned
provider details, and lists the created assets. Set the
Main Sequence secret `OPEN_FIGI_API_KEY` in
`www.main-sequence.app/app/main_sequence_workbench/secrets` before running the
workflow. Cleanup is disabled by default.

The local FastAPI surface under `apps/v1` now exposes the migrated asset and
asset-category registry routes. Keep the route layer thin and put reusable
catalog/category logic under `src/msm/services`. The implemented category detail
flow uses `GET /api/v1/asset-category/{uid}/` plus the nested asset list route
`GET /api/v1/asset/?categories__uid=<uid>`. The same local API surface now also
exposes the simple index registry routes:

- `GET /api/v1/index/`
- `GET /api/v1/index/{uid}/`
- `DELETE /api/v1/index/{uid}/`

When `MSM_AUTO_REGISTER_NAMESPACE` is set for this local API, startup now
pre-registers the full `apps/v1` table set against the real project/session
data source already configured for the Main Sequence client. If the session
cannot resolve a valid DynamicTable data source, startup should fail and that
platform/data-source issue should be fixed directly.

See [FastAPI v1](../fast_api/v1/index.md) for the current route inventory and
contract notes.

## Currency Assets

Single currencies and currency spot pairs are separate assets. Create or resolve
the component currency assets first, then let `CurrencySpot.upsert(...)` own the
spot-pair asset and `CurrencySpotAssetDetailsTable` write:

```python
from msm.api.assets import Asset, CurrencySpot
from msm.constants import ASSET_TYPE_CURRENCY

USD = {"code": "USD", "currency_name": "US Dollar"}
EUR = {"code": "EUR", "currency_name": "Euro"}

usd = Asset.upsert(unique_identifier=USD["code"], asset_type=ASSET_TYPE_CURRENCY)
eur = Asset.upsert(unique_identifier=EUR["code"], asset_type=ASSET_TYPE_CURRENCY)

eur_usd = CurrencySpot.upsert(
    unique_identifier="BBG0013HGRV5",
    base_currency_uid=eur.uid,
    quote_currency_uid=usd.uid,
)
```

Typed asset APIs normalize asset type keys before writing them, so `"Currency"`
is stored as `currency`, `"Currency Spot"` is stored as `currency_spot`, and
`"Future"` is stored as `future`.

See `examples/msm/assets/currency_spot_workflow.py` and
[Currency Assets](../knowledge/msm/assets/currency.md) for the detailed schema and
workflow.

## Bond Assets

Bond setup uses reference issuers plus canonical asset rows. Create the issuer
and denomination currency first, then let `Bond.upsert(...)` own the bond asset
and `BondAssetDetailsTable` write:

```python
import datetime as dt

from msm.api.assets import Asset, AssetType, Bond
from msm.api.issuers import Issuer
from msm.constants import (
    ASSET_TYPE_BOND_DEFINITION,
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_DEFINITION,
)

AssetType.upsert(**ASSET_TYPE_CURRENCY_DEFINITION.as_payload())
AssetType.upsert(**ASSET_TYPE_BOND_DEFINITION.as_payload())

issuer = Issuer.upsert(
    unique_identifier="example-issuer",
    display_name="Example Issuer",
)
usd = Asset.upsert(unique_identifier="USD", asset_type=ASSET_TYPE_CURRENCY)

bond = Bond.upsert(
    unique_identifier="example-usd-bond-2031",
    issuer_uid=issuer.uid,
    currency_asset_uid=usd.uid,
    issue_date=dt.date(2026, 5, 27),
    maturity_date=dt.date(2031, 5, 27),
    status="ACTIVE",
)
```

See `examples/msm/assets/bond_workflow.py` and
[Bond Assets](../knowledge/msm/assets/bonds.md) for the detailed schema and
workflow. `examples/msm/assets/us_treasury_bond_workflow.py` shows the same API on
a US Treasury note where CUSIP maps to canonical asset identity, FIGI maps to
provider details, and coupon/tenor fields stay outside the minimal bond detail
table.

## Asset Snapshots

`AssetSnapshot` is a DataNode, not a MetaTable. Build validated snapshot frames
or a configured node through `AssetSnapshot` methods. Construct the node first,
then bind rows whose payloads each carry their own `time_index`:

```python
from datetime import datetime, UTC

from msm.data_nodes.assets import AssetSnapshot

snapshot_node = AssetSnapshot().set_snapshots(
    {
        "time_index": datetime.now(UTC),
        "unique_identifier": "example-asset-btc",
        "ticker": "BTC",
    },
)
snapshot_frame = snapshot_node.run(debug_mode=True, force_update=True)
```

Markets DataNodes use the same identifier rule as MetaTables. With the default
markets namespace, logical identifiers stay bare, such as `Asset` and
`AssetSnapshotsTS`. With `MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples`,
the published identifiers become `mainsequence.examples.Asset` and
`mainsequence.examples.AssetSnapshotsTS`; the default DataNode `hash_namespace`
is also `mainsequence.examples`. Pass explicit `identifier` or `hash_namespace`
only when a test or experiment needs isolation.

Asset snapshot source tables have a canonical foreign key from
`unique_identifier` to `AssetTable.unique_identifier`, so the `Asset` MetaTable
must exist before a snapshot DataNode initializes its source table. In examples
that perform source-table initialization, run `msm.start_engine(models=["Asset"])`
with the intended namespace before creating the DataNode.

Before the write path persists rows, `AssetSnapshot` checks the backend for the
incoming `(time_index, unique_identifier)` tuples and fails if any tuple already
exists. Publish corrections as a new timestamped snapshot instead of overwriting
the existing row.

See `examples/msm/assets/asset_crud_workflow.py` for the workflow that also writes
an `AssetSnapshot` frame. See
[Asset-Indexed DataNodes](../knowledge/msm/assets/asset_indexed_data_nodes.md) for
the detailed `AssetIndexedDataNode` contract and how `AssetSnapshot` implements
it.

When the universe itself should be a reusable platform object, create an asset
category and manage memberships separately:

```python
from msm.api.assets import Asset, AssetCategory, AssetType
from msm.constants import ASSET_TYPE_CRYPTO, ASSET_TYPE_CRYPTO_DEFINITION

AssetType.upsert(**ASSET_TYPE_CRYPTO_DEFINITION.as_payload())

btc = Asset.upsert(unique_identifier="BTC", asset_type=ASSET_TYPE_CRYPTO)
eth = Asset.upsert(unique_identifier="ETH", asset_type=ASSET_TYPE_CRYPTO)
category = AssetCategory.upsert(
    unique_identifier="crypto-majors",
    display_name="Crypto Majors",
)
memberships = AssetCategory.replace_memberships(
    category_uid=category.uid,
    asset_uids=[btc.uid, eth.uid],
)
```

For a step-by-step membership lifecycle, run
`examples/msm/assets/asset_category_workflow.py`. It creates a category, adds
assets, removes assets, and prints the category contents after each change. The
normal run leaves assets in the category unless the cleanup flag is used. Asset
examples reuse shared identifiers and FIGI constants from
`examples/msm/assets/utils/reference_data.py`.

## Accounts, Funds, And Portfolios

```python
import msm_portfolios

from msm.api.accounts import Account
from msm_portfolios.api.portfolios import Portfolio
from msm_portfolios.api.virtual_funds import Fund

msm_portfolios.start_engine(models=["Account", "Portfolio", "Fund"])

account = Account.upsert(
    unique_identifier="acct-main",
    account_name="Main Account",
)
portfolio = Portfolio.upsert(
    unique_identifier="btc-eth-target",
    calendar_name="24/7",
)
fund = Fund.upsert(
    unique_identifier="fund-core",
    target_account_uid=account.uid,
    target_portfolio_uid=portfolio.uid,
)
```

## Holdings And Target Positions

See `examples/msm_portfolios/portfolio_equal_weights_example.py` for the portfolio
workflow that creates the optional portfolio `Index`, prepares `SignalWeights`,
`PortfolioWeights`, and `PortfoliosDataNode`, and stores their DataNode UIDs on
the `Portfolio` row.

```python
from msm.api.accounts import AccountTargetPortfolio, PositionSet
from msm.services import build_account_holdings_frame, build_target_positions_frame

holdings = build_account_holdings_frame(
    holdings_date="2026-05-25T00:00:00Z",
    account_uid=account.uid,
    positions=[
        {"unique_identifier": "BTC", "quantity": 1.0},
        {"unique_identifier": "ETH", "quantity": 10.0},
    ],
)

account_target_portfolio = AccountTargetPortfolio.upsert(
    unique_identifier="account-main-balanced-target",
    account_uid=account.uid,
    account_model_portfolio_uid=model_portfolio.uid,
)
position_set = PositionSet.upsert(
    account_target_portfolio_uid=account_target_portfolio.uid,
    position_set_time="2026-05-25T00:00:00Z",
)

targets = build_target_positions_frame(
    target_positions_date="2026-05-25T00:00:00Z",
    position_set_uid=position_set.uid,
    positions=[
        {"unique_identifier": "BTC", "weight_notional_exposure": 0.6},
        {"unique_identifier": "ETH", "weight_notional_exposure": 0.4},
    ],
)
```

The DataNode frame helpers validate the dynamic-table contract locally. The
actual table provisioning and writes remain generic TDAG/DataNode behavior.
