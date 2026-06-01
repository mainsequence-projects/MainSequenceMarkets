# Floating-Rate Bond Pricing Example

This example shows the complete pricing workflow for a bond asset:

1. register the bond asset type, issuer, currency asset, and bond asset
2. register the `interest_rate` index type, a canonical index, its pricing convention details, and a curve identity
3. publish one month of mock index fixings and a flat-forward discount curve through pricing DataNodes
4. use the seeded `default` pricing market-data bindings for `discount_curves`
   and `interest_rate_index_fixings`
5. attach a serialized `FloatingRateBond` to the bond asset
6. reload the instrument generically with `Instrument.load_from_asset(...)`
7. price the bond and print analytics, expected coupons, and carry/roll-down output

Run it from the project root after installing the pricing extra:

```bash
uv sync --extra pricing
uv run python examples/pricing/bond_pricing_example/main.py
```
