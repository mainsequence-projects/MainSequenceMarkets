# Floating-Rate Bond Pricing Example

This example shows the complete pricing workflow for a bond asset:

1. upsert the bond asset type, issuer, currency asset, and bond asset rows
2. upsert the `interest_rate` index type, a canonical index, its pricing convention details, a curve identity, curve build details, and a market-data-set curve binding
3. publish one month of mock index fixings and a flat-forward discount curve through pricing DataNodes
4. use explicit `default` pricing market-data bindings for `discount_curves`
   and `interest_rate_index_fixings`
5. attach a serialized `FloatingRateBond` to the bond asset
6. reload the instrument generically with `Instrument.load_from_asset(...)`
7. price the bond and print analytics, expected coupons, and carry/roll-down output

Run it from the project root after installing the pricing extra:

```bash
uv sync --extra pricing
mainsequence migrations upgrade --provider migrations:migration head
uv run python examples/msm_pricing/bond_pricing_example/main.py
```

The migration step must complete before the script starts. The script uses
`msm.start_engine(...)` and `msm_pricing.bootstrap.attach_pricing_schemas(...)`
only to attach already-migrated MetaTables and configure pricing runtime state.

The discount-curve DataNode returns `key_nodes` as a top-level storage column
beside the compressed `curve` payload. `key_nodes` is source-owned JSON
provenance. The mock flat-forward publisher uses the recommended `CurveKeyNode`
shape with `maturity_date`, `instrument_type`, `quote`, `quote_type`,
`quote_unit`, `quote_side`, and yield-native `yield` values. Producers may use
their own JSON schema when that is needed to audit the source build;
`CurveBuildingDetails` still owns the final constructed curve convention.
Real source publishers that need stricter checks should override
`DiscountCurvesNode.normalize_key_nodes(...)` or attach
`set_key_nodes_validator(...)` instead of changing the shared storage schema.

The example writes the projection curve selection as the default quote-side
binding (`quote_side=None`) because the valuation basket passes only
`market_data_set`. If a workflow writes `quote_side="mid"` instead, runtime calls
must pass the same quote side, for example `price(curve_quote_side="mid")`.
