# Floating-Rate Bond Pricing Example

This example shows the complete pricing workflow for a bond asset:

1. upsert the bond asset type, issuer, currency asset, and bond asset rows
2. upsert the `interest_rate` index type, a canonical index, its pricing convention details, and a curve identity
3. publish one month of mock index fixings and a flat-forward discount curve through pricing DataNodes
4. use the seeded `default` pricing market-data bindings for `discount_curves`
   and `interest_rate_index_fixings`
5. attach a serialized `FloatingRateBond` to the bond asset
6. reload the instrument generically with `Instrument.load_from_asset(...)`
7. price the bond and print analytics, expected coupons, and carry/roll-down output

Run it from the project root after installing the pricing extra:

```bash
uv sync --extra pricing
mainsequence migrations upgrade --provider msm.migrations:migration head
uv run python examples/msm_pricing/bond_pricing_example/main.py
```

The migration step must complete before the script starts. The script uses
`msm.start_engine(...)` and `msm_pricing.bootstrap.create_pricing_schemas(...)`
only to attach already-migrated MetaTables and configure pricing runtime state.
