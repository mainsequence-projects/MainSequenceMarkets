# Portfolios

Construct an equal-weights portfolio end to end. The workflow runs in two
stages: a schema-preparation step that provisions the interpolated price
storage, then a run step that publishes prices, computes weights, and stores the
portfolio DataNode result. It reuses the calendar from
[Calendars](02-calendars.md) as `Portfolio.calendar_uid`.

For the runtime model behind these row APIs, see [Core Concepts](../concepts.md).

## Two-stage equal-weights workflow

Run the portfolio workflow in two stages:

```bash
python examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py
python examples/msm_portfolios/portfolio_equal_weights_run.py
```

The preparation script derives the configured interpolated price storage from
the registered `ExternalPricesStorage` table and the example interpolation
policy, finds or generates the real dynamic Alembic revision under the active
migration namespace, and runs the dynamic provider upgrade before portfolio
DataNodes write. If an older registered `ExternalPricesStorage` table is missing
cadence metadata, the preparation step repairs that source metadata before
deriving the dynamic interpolation table. The run script creates the
optional portfolio `Index`, publishes example OHLCV source bars to
`ExternalPricesStorage`, interpolates prices, runs `SignalWeights`,
`PortfolioWeights`, and `PortfoliosDataNode`, creates or reuses the crypto
`CRYPTO_24_7` calendar, and stores the calendar, index, and DataNode UIDs on the
`Portfolio` row. The price configuration stores the
`ExternalPricesStorage` TimeIndexMetaTable UID on `InterpolatedPricesConfig`, so
the explicit upstream interpolation node can recover the price source through
the SDK APIDataNode lookup path. The portfolio configuration receives that
`InterpolatedPrices` node as `valuation_source_instance` and sets
`valuation_column="close"`; `PortfoliosDataNode` does not create interpolation
storage internally. Real portfolio extensions can pass any compatible
asset-indexed valuation DataNode or APIDataNode and choose any numeric valuation
column, such as `fair_value` or `nav`, without reshaping the source into OHLC
bars. A focused configuration example is available at
`examples/msm_portfolios/portfolio_custom_valuation_column_example.py`:

```bash
python examples/msm_portfolios/portfolio_custom_valuation_column_example.py \
  --source-time-index-meta-table-uid <fair-value-time-index-meta-table-uid>
```

The source bar frequency is read from the registered source table's cadence
metadata, then used with `__metatable_extra_hash_components__` to select a
configured output storage table, so different source cadence, upsample
frequency, and interpolation rule combinations do not collide inside one price
table. The script prints the workflow steps, created row UIDs, source valuation
row counts, explicit valuation-source dependency details, and published DataNode
storage UIDs.

**Next →** [Pricing Instruments](05-pricing.md)
