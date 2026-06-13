# 0033. Pricing Valuation Position Boundary

## Status

Proposed

## Context

`msm_pricing` currently has an exported `Position` object under
`msm_pricing.instruments.position`. It is an in-memory Pydantic object that
contains `PositionLine` entries:

```text
Position
  position_date optional
  lines:
    instrument
    units
    extra_market_info optional
```

The current class is not a SQLAlchemy model, is not part of
`msm_pricing.models`, and is not included in `pricing_sqlalchemy_models()`.
There is no pricing `PositionTable` today.

The current pricing architecture has moved away from that older shape:

- instrument terms are identity-free Pydantic payloads;
- durable asset linkage lives in `AssetCurrentPricingDetailsTable` and
  `AssetPricingDetailsStorage`;
- pricing market-data source selection is explicit through
  `PricingMarketDataSet` and `PricingMarketDataSetBinding`;
- instruments are valued for an explicit valuation date through
  `InstrumentModel.set_valuation_date(...)`;
- bond and swap pricing methods accept market-data-set context.

The old `Position` class does not participate in that lifecycle. It is exported
and mentioned in package documentation, but it has no tests or examples in the
current repository.

## Current Implementation Problems

The existing `Position` object should be treated as legacy for these reasons:

1. It does not apply `position_date` to the contained instruments. Current
   instruments require `set_valuation_date(...)` before pricing.
2. `Position.price()` does not accept `valuation_date` or `market_data_set`, so
   pricing context must be hidden in pre-mutated instrument instances.
3. It calls `instrument.price()` with no arguments, even though current
   instruments can require market-data-set selection.
4. It assumes `instrument.content_hash()`, but `InstrumentModel` does not define
   that method.
5. It has stale registry setup for option instrument names that are not current
   package exports.
6. It silently skips instruments without expected cashflow methods. Valuation
   workflows should fail clearly when a requested valuation output cannot be
   produced.
7. `extra_market_info` is untyped and does not define a stable valuation input
   contract.
8. The name `Position` collides with account and portfolio position concepts.
   Account holdings, target positions, and portfolio weights are business
   exposure concepts; pricing should consume them, not redefine ownership.

The useful concept is still valid:

```text
instrument + units + valuation context
```

But that concept should be explicit and valuation-scoped, not a persisted
position registry and not a vague package-level `Position` object.

## Decision

Do not introduce a pricing `PositionTable` now.

Replace the old `msm_pricing.Position` public concept with an explicit
in-memory valuation basket. The target naming should avoid pretending that
pricing owns business positions. Preferred names:

```text
ValuationLine
ValuationPosition
```

`ValuationPosition` is a transient valuation input. It links priceable
instrument terms to units for one valuation context.

Target shape:

```python
class ValuationLine(BaseModel):
    instrument: InstrumentModel
    units: float
    asset_uid: UUID | None = None
    metadata_json: dict[str, Any] = {}


class ValuationPosition(BaseModel):
    valuation_date: datetime
    market_data_set: PricingMarketDataSetSelector = None
    lines: list[ValuationLine]
```

The required semantics are:

- `valuation_date` is required at the basket level.
- `market_data_set` is selected at the basket level for the first
  implementation.
- `units` is a multiplier on the instrument-defined economics.
- Each instrument is valued only after the basket applies the valuation date.
- Pricing failures are strict. If a requested output cannot be produced for one
  line, the basket valuation fails instead of silently dropping the line.
- `asset_uid` is optional because ad hoc instrument valuation may not be tied to
  a persisted asset. When present, it is the canonical asset reference for the
  line, not a generic provenance mechanism.
- `metadata_json` is optional caller metadata. It must not be required for core
  pricing semantics.

The valuation basket may expose methods such as:

```python
position.price()
position.analytics()
position.price_breakdown()
position.get_cashflows()
position.get_net_cashflows()
```

Those methods should consistently:

1. set the valuation date on every instrument;
2. pass `market_data_set` to instrument methods that accept it;
3. scale per-line values by `units`;
4. include enough line-level detail in breakdown outputs to map results back to
   the submitted input order and optional `asset_uid`;
5. fail loudly on unsupported output requests.

## Unit Semantics

`units` is not the instrument definition. It is the quantity multiplier applied
to an already defined instrument.

For example, a bond instrument still owns economics such as face value,
schedule, coupon, index reference, spread, and redemption terms. The valuation
line owns how many such instrument units are held for this valuation.

Adapters from accounts or portfolios must normalize their domain quantity into
this contract. If an upstream account stores nominal amount, the adapter must
choose a consistent conversion into:

```text
instrument economic notional
units multiplier
```

That conversion belongs at the adapter boundary, not inside the low-level
instrument pricing methods.

## Ownership Boundary

Pricing owns valuation of instrument terms.

Pricing does not own durable business position state:

- account holdings remain account data;
- target positions remain account allocation data;
- portfolio weights remain portfolio construction data;
- valuation baskets are transient unless a later ADR defines valuation-run
  persistence.

Future persistence should not start with a generic `PositionTable` in
`msm_pricing`. If persistence is needed later, model the actual durable concept:

- account or portfolio position state, owned by `msm` or `msm_portfolios`; or
- valuation-run audit input/output, owned by `msm_pricing` only if the purpose
  is reproducible pricing audit.

## Construction Paths

The valuation basket should support multiple sources without owning them:

1. **Ad hoc valuation**: caller passes instruments and units directly.
2. **Asset valuation**: caller supplies asset rows and units; pricing loads the
   relevant instrument payload from pricing details.
3. **Account valuation**: account services provide asset exposure rows; an
   adapter turns them into valuation lines.
4. **Portfolio valuation**: portfolio services provide asset weights,
   quantities, or notional exposures; an adapter turns them into valuation
   lines.
5. **Mixed valuation**: callers can combine lines from several sources as long
   as they normalize each source into the same minimal line contract.

`ValuationPosition` should not query account or portfolio tables by itself.
Those packages own their own source selection and should pass normalized
valuation lines into pricing.

The first implementation should not add generic `source_type` or `source_uid`
fields. Those fields are too arbitrary without a concrete consumer. If an
account or portfolio adapter needs provenance later, that adapter should own its
own mapping or a later ADR should introduce a specific provenance contract.

## Non-Goals

This ADR does not:

- create a pricing `PositionTable`;
- define persisted valuation-run tables;
- define generic source/provenance fields such as `source_type` and
  `source_uid`;
- make `msm_pricing` own account holdings or portfolio weights;
- add portfolio construction behavior to pricing;
- preserve the old `Position` API as a compatibility surface.

## Consequences

Positive consequences:

- valuation context becomes explicit;
- account and portfolio ownership boundaries stay clean;
- pricing can value arbitrary baskets without pretending to own business
  positions;
- future persistence can be designed around the real durable artifact.

Costs:

- callers using `msm_pricing.Position` must migrate;
- pricing examples and docs need to move to the new valuation-basket API;
- tests must cover strict failure behavior and context propagation.

## Implementation Tasks

- [ ] Remove `Position` and `PositionLine` from the top-level `msm_pricing`
      exports.
- [ ] Remove or replace `src/msm_pricing/instruments/position.py`.
- [ ] Add the new in-memory valuation-basket implementation under a clear
      module such as `msm_pricing.valuation`.
- [ ] Add tests proving `valuation_date` is applied to every instrument before
      valuation.
- [ ] Add tests proving `market_data_set` is passed through to supported
      instrument methods.
- [ ] Add tests proving price, analytics, and cashflow outputs are scaled by
      `units`.
- [ ] Add tests proving unsupported requested outputs fail clearly instead of
      silently dropping lines.
- [ ] Add an example showing ad hoc fixed-income valuation from instruments and
      units.
- [ ] Add adapter examples or docs for account/portfolio sources once those
      workflows need basket valuation.
- [ ] Update `src/msm_pricing/README.md`,
      `docs/knowledge/msm_pricing/index.md`, and the pricing tutorial text to
      remove the old `Position` surface and document the valuation basket.
- [ ] Update the pricing skill after implementation so agents stop recommending
      `msm_pricing.Position`.

## Open Questions

- Should line-level `market_data_set` overrides be supported later, or should a
  valuation basket always be homogeneous by market-data set?
- Should `asset_uid` be required for all lines loaded from persisted pricing
  details, while remaining optional for ad hoc instruments?
- Should the first implementation provide helpers that load instruments from
  assets in bulk, or should that stay in `msm_pricing.api` next to pricing
  details persistence?
- If valuation-run persistence is added later, should it store instrument dumps,
  references to pricing detail rows, or both?
