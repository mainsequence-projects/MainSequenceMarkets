# 0029. Account Holdings To Virtual Fund Allocation Policy

## Status

Accepted - first implementation landed

This ADR defines the business logic and implementation plan for allocating real
account holdings into virtual-fund holdings. The first implementation moves
virtual-fund identity and storage into core `msm`, adds a pure vector planner,
adds deterministic input resolution from `PositionSetTable.uid`, and adds an
apply step for feasible plans. The remaining schema follow-up is adding
`VirtualFundTable.account_target_allocation_uid` so virtual-fund identity is
relational, not only encoded in the deterministic business key.

## Context

Account holdings are the canonical record of what the account actually holds:

```text
AccountTable
  <- AccountHoldingsSetTable
       <- AccountHoldingsStorage
            time_index
            account_uid
            asset_identifier
            quantity
            direction
```

Account target allocations describe mandate intent:

```text
AccountTargetAllocationTable
  <- PositionSetTable
       <- TargetPositionsStorage
            target_type = asset | portfolio
            asset_uid
            portfolio_uid
            weight_notional_exposure
            constant_notional_exposure
            single_asset_quantity
```

Virtual funds are allocation views over real account holdings:

```text
VirtualFundTable
  account_uid
  target_portfolio_uid

VirtualFundHoldingsSetTable
  virtual_fund_uid
  source_account_holdings_set_uid

VirtualFundHoldingsStorage
  virtual_fund_uid
  asset_identifier
  allocated_quantity
  direction
```

The allocation service is the business logic that turns:

```text
real account holdings
+ account target allocation / PositionSet
+ portfolio weights
+ valuations / NAV
+ allocation policy
= virtual-fund allocation rows
```

The service must not invent virtual-fund holdings from hardcoded quantities.
Portfolio construction does not imply how much of an account should be funded
into a virtual fund. That funding decision belongs to an explicit account
allocation policy derived from the account's target allocation.

## Principle

`AccountHoldingsStorage` remains canonical custody state. Virtual-fund holdings
are a derived allocation view over those holdings. They must be reproducible
from a source holdings set, a target position set, portfolio weights,
valuation outputs, and an explicit allocation policy.

The allocation service must first produce a dry-run allocation plan. Publishing
`VirtualFundHoldingsStorage` rows is a separate apply step.

## Core Example

Assume:

```text
Account holds:
  10 BTC
  20 ETH

Valuation numeraire:
  USD cash asset represented by AssetTable.uid = USD_ASSET_UID

Simple spot valuation inputs:
  BTC = 60,000 units of USD_ASSET_UID
  ETH = 2,000 units of USD_ASSET_UID

Account NAV:
  BTC value = 10 * 60,000 = 600,000 units of USD_ASSET_UID
  ETH value = 20 * 2,000  =  40,000 units of USD_ASSET_UID
  account_nav = 640,000 units of USD_ASSET_UID

Account target row:
  target_type = portfolio
  weight_notional_exposure = 10%
  constant_notional_exposure = null
  portfolio_uid = P

Portfolio P weights:
  BTC = 40%
  ETH = 60%
```

The virtual fund should not receive arbitrary BTC or ETH quantities. In this
weight-based case, its total notional is:

```text
portfolio_sleeve_notional = account_nav * 10%
                           = 640,000 * 10%
                           = 64,000 USD
```

That sleeve notional is expanded through the portfolio weights:

```text
BTC notional = 64,000 * 40% = 25,600 USD
ETH notional = 64,000 * 60% = 38,400 USD

BTC quantity = 25,600 / 60,000 = 0.4266666667 BTC
ETH quantity = 38,400 / 2,000  = 19.2 ETH
```

If the account target row uses a fixed notional instead:

```text
target_type = portfolio
weight_notional_exposure = null
constant_notional_exposure = 50,000 USD
portfolio_uid = P
```

then the sleeve notional is independent of NAV:

```text
portfolio_sleeve_notional = 50,000 USD
```

and the expanded asset demand is:

```text
BTC notional = 50,000 * 40% = 20,000 USD
ETH notional = 50,000 * 60% = 30,000 USD

BTC quantity = 20,000 / 60,000 = 0.3333333333 BTC
ETH quantity = 30,000 / 2,000  = 15 ETH
```

For the weight-based example, the account has enough BTC and ETH to fund the
virtual-fund target:

```text
available BTC = 10 BTC
required BTC  = 0.4266666667 BTC
residual BTC  = 9.5733333333 BTC

available ETH = 20 ETH
required ETH  = 19.2 ETH
residual ETH  = 0.8 ETH
```

Those residual holdings remain real account holdings. They may stay unallocated,
be used to satisfy direct asset targets, or be used by other virtual-fund
targets depending on the full account target allocation and allocation policy.

## Deterministic Resolution Paths

The planner intentionally starts from one authoritative row:
`PositionSetTable.uid`. It does not accept `account_uid`,
`source_account_holdings_set_uid`, or portfolio weight sources as primary
inputs.

Account and source holdings are resolved through one path:

```text
PositionSetTable.uid = position_set_uid
  -> PositionSetTable.account_target_allocation_uid
  -> AccountTargetAllocationTable.uid
  -> AccountTargetAllocationTable.account_uid
  -> AccountTable.uid
  -> AccountHoldingsSetTable rows for that account
```

The default holdings selection policy is exact:

```text
AccountHoldingsSetTable.account_uid = derived account_uid
AccountHoldingsSetTable.time_index = valuation_time
```

`AccountHoldingsSetTable` already has a unique `(account_uid, time_index)` path,
so the default policy produces at most one source holdings set. If the selected
policy resolves zero or more than one source holdings set, the planner must fail
before loading holdings rows.

Portfolio weights are resolved from the portfolio target row:

```text
TargetPositionsStorage.portfolio_uid
  -> PortfolioTable.uid
  -> PortfolioTable.portfolio_index_uid
  -> IndexTable.uid
  -> IndexTable.unique_identifier
  -> PortfolioWeightsStorage rows
       where portfolio_index_identifier = IndexTable.unique_identifier
       and time_index = valuation_time
```

If `PortfolioTable.portfolio_index_uid` is missing, the referenced `IndexTable`
row is missing, or no portfolio weights exist for the selected time, the planner
fails by default. Latest-available weights may be accepted only when
`allocation_policy` explicitly allows that selection rule, and the resolved
weight timestamp must be recorded in diagnostics.

## Inputs

The allocation planner requires:

| Input | Type | Required relationship / FK check | Meaning |
| --- | --- | --- | --- |
| `position_set_uid` | `uuid.UUID` | Must exist as `PositionSetTable.uid`; `PositionSetTable.account_target_allocation_uid -> AccountTargetAllocationTable.uid`; `AccountTargetAllocationTable.account_uid -> AccountTable.uid`. | Concrete target allocation snapshot to satisfy. This is the authoritative account context. |
| `valuation_time` | timezone-aware UTC `datetime.datetime` | Used to select valuations, conversions, portfolio weights, and target/holdings snapshots. It must be normalized to UTC before planning. | Time at which NAV and target quantities are calculated. |
| `valuation_asset_uid` | `uuid.UUID` | Must exist as `AssetTable.uid`; this asset is the canonical valuation numeraire. | Asset used for account NAV, fixed notional targets, quantity conversion, and diagnostics. |
| `holdings_selection_policy` | typed policy object | Must resolve exactly one `AccountHoldingsSetTable` row for the account derived from `position_set_uid`; default is exact `AccountHoldingsSetTable.time_index == valuation_time`. | Selects the canonical source holdings snapshot without accepting a raw holdings-set UID. |
| `valuation_resolver` | batch protocol / callable | Planner calls it with requested valuation metrics, resolved source holdings, target notional demands, `valuation_time`, `valuation_asset_uid`, and valuation rules from `allocation_policy`. For this allocation planner, `nav` is required. | Owns instrument valuation, metric calculation, NAV contribution, and notional-to-quantity conversion. |
| `allocation_policy` | typed policy object, default `proportional_attribution` | Must define attribution mode, shortage behavior, residual behavior, leverage permission, stale data tolerance, rounding tolerance, and idempotency mode. | Governs how real holdings are attributed when holdings and target demand do not match exactly. |

Resolver contracts:

```text
valuation_resolver(
  requested_metrics: collection[str],
  source_holdings: collection[HoldingValuationInput],
  target_notional_demands: collection[TargetNotionalDemand],
  *,
  valuation_time: datetime,
  valuation_asset_uid: uuid.UUID,
  valuation_policy: ValuationPolicy,
)
  -> AllocationValuation

required metric for this planner:
  "nav"

examples of future metrics using the same protocol:
  "var"
  "vol"
  "duration"
  "dv01"

HoldingValuationInput
  asset_uid: uuid.UUID
  asset_identifier: str
  quantity: Decimal | float
  direction: 1 | -1
  source_row: mapping

TargetNotionalDemand
  target_row_key: str
  asset_uid: uuid.UUID
  asset_identifier: str
  notional_value: Decimal | float
  direction: 1 | -1

AllocationValuation
  metrics: dict[str, ValuationMetricResult]
  valuation_asset_uid: uuid.UUID
  valuation_asset_identifier: str
  target_quantity_demands: list[TargetQuantityDemand]
  diagnostics: list[ValuationDiagnostic]

ValuationMetricResult
  metric: str
  total: ValuationMetricValue
  lines: list[ValuationMetricLine]

ValuationMetricValue
  value: Decimal | float | mapping
  valuation_asset_uid: uuid.UUID | None
  as_of: datetime
  source: str | None

ValuationMetricLine
  line_key: str
  asset_uid: uuid.UUID | None
  asset_identifier: str | None
  source_row_key: str | None
  target_row_key: str | None
  value: Decimal | float | mapping
  valuation_asset_uid: uuid.UUID | None
  as_of: datetime
  source: str | None

TargetQuantityDemand
  target_row_key: str
  asset_uid: uuid.UUID
  asset_identifier: str
  requested_signed_quantity: Decimal | float
  direction: 1 | -1
  requested_notional: Decimal | float
```

`asset_uid` is the authoritative valuation subject. The planner may provide the
resolved `AssetTable.unique_identifier` as metadata because current
asset-indexed storage is keyed by `asset_identifier`, but the resolver contract
must not use ticker, ISIN, FIGI, or provider symbols as the primary asset key.
`valuation_asset_uid` is the authoritative numeraire. If a valuation provider
needs ISO-4217 currency codes or provider symbols, that mapping belongs inside
the resolver from `AssetTable.uid` to provider-specific identifiers. The planner
contract stays on canonical asset identity. `ValuationPolicy` is the valuation
sub-policy carried by `allocation_policy`; it is not another top-level planner
input.

The valuation protocol is metric-based. The allocation service currently
requires the `nav` metric because portfolio sleeve notional is defined from NAV
or fixed notional exposure. Other consumers can request metrics such as `var`,
`vol`, `duration`, or `dv01` through the same resolver without changing the
resolver interface. A resolver may reject unsupported metrics explicitly.

Metric results must support both totals and line results. Totals are used for
account-level decisions such as account NAV. Lines are used for audit,
reconciliation, and per-asset allocation checks. A line can be tied to an
`asset_uid`, a source holding row, a target demand row, or any combination that
is meaningful for the requested metric.

The valuation resolver owns instrument-specific valuation. For a simple spot
asset, it may compute `quantity * spot_price`. For a derivative, structured
product, accrued-income instrument, or any other non-linear exposure, it may use
contract metadata, model configuration, curves, greeks, multipliers, accrued
interest, or other domain inputs. The allocation planner must not encode those
cases.

Weights are signed notional weights. A negative weight produces short demand.
Weights do not need to sum to `1.0`; if they sum above `1.0`, the target
portfolio is leveraged and must be allowed by policy.

The planner must load:

```text
PositionSetTable row
  where uid = position_set_uid

AccountTargetAllocationTable row
  from PositionSetTable.account_target_allocation_uid

AccountHoldingsSetTable row
  by derived account_uid and holdings_selection_policy

AccountHoldingsStorage rows
  where holdings_set_uid = resolved AccountHoldingsSetTable.uid

TargetPositionsStorage rows
  where position_set_uid = position_set_uid

Portfolio weights
  for every portfolio target row

AssetTable rows
  for every held asset_identifier and every target asset_uid

Valuations
  for source holdings and target notional demands
```

## NAV Calculation

Default account NAV is provided by the valuation resolver at `valuation_time`
in `valuation_asset_uid`:

```text
valuation_result = valuation_resolver(requested_metrics=("nav",), ...)
account_nav      = valuation_result.metrics["nav"].total.value
```

For auditability, the resolver must also return NAV line results whose sum
reconciles to `account_nav` within policy tolerance. For normal asset holdings,
those lines should be keyed by `asset_uid` and source row. For instruments that
cannot be naturally decomposed per asset, the resolver may return a model-level
line with `asset_uid=None` and explicit diagnostics:

```text
account_nav = sum(valuation_result.metrics["nav"].lines[*].value)
```

Rules:

- Missing valuation data is an error by default.
- Missing conversion into `valuation_asset_uid` is an error by default.
- Negative or zero NAV is an error for weight-based allocation unless the
  caller explicitly allows it.
- Cash should be represented as a normal asset row or an explicit future cash
  balance input. The initial service must not silently invent cash.
- Stale valuations are accepted only when the caller provides a valuation policy
  that allows latest-available data.

## Target Demand Expansion

Target rows produce demand against the account NAV or explicit quantity.

Direct asset rows:

```text
target_type = asset
```

Direct asset rows describe the desired direct account exposure. They are not
virtual-fund allocations, but they must be considered when deciding what source
holdings remain available for virtual funds.

Portfolio rows:

```text
target_type = portfolio
```

Portfolio rows produce virtual-fund demand. For each portfolio target row:

```text
portfolio_sleeve_notional =
  account_nav * weight_notional_exposure
  or constant_notional_exposure

expanded_asset_notional =
  portfolio_sleeve_notional * portfolio_weight(asset_uid)

expanded_signed_quantity =
  valuation_result.target_quantity_demands[target_row_key].requested_signed_quantity

direction =
  1  if expanded_asset_notional >= 0
  -1 if expanded_asset_notional < 0
```

`single_asset_quantity` is valid for direct asset targets only. It is not a
valid portfolio target exposure unless a later ADR defines portfolio units.

If portfolio weights are leveraged or short, the sign of
`portfolio_sleeve_notional * portfolio_weight(asset_uid)` determines the
requested target direction. The sign is preserved on the claim. Under
`proportional_attribution`, opposite-signed virtual-fund claims do not net
against each other. Direct account targets are not fill competitors; the direct
account sleeve is the balancing residual after virtual-fund allocation.

## Allocation Pools

The planner builds signed account holding vectors from real account holdings:

```text
AccountHoldingsStorage.asset_identifier
  -> AssetTable.unique_identifier
  -> AssetTable.uid

holding key = asset_uid
signed_account_holding = sum(quantity * direction)
gross_source_capacity = sum(abs(quantity))
```

The planner builds a virtual-fund target matrix from portfolio target rows:

```text
virtual_target[virtual_fund_uid, asset_uid] = requested_signed_quantity
```

It also builds the aggregate desired direct account target:

```text
direct_target[asset_uid] = sum(requested_signed_quantity for direct asset rows)
```

The direct target is diagnostic intent. It does not enter the virtual-fund fill
denominator. The direct sleeve is computed later as the residual required to
make the account reconcile to real holdings.

The planner builds target demands:

```text
direct demand:
  from target_type = asset

virtual-fund demand:
  from target_type = portfolio expanded through portfolio weights
```

The planner must compare virtual-fund demand against the asset-level gross
source capacity. This matters because multiple virtual funds can compete for
the same BTC, ETH, cash, or signed exposure budget. Direct account targets do
not compete for that fill; they are measured against the residual direct
sleeve.

The planner also builds virtual-fund allocation claims. A claim is a desired
virtual-fund exposure against one asset-level capacity vector:

```text
claim key = (claim_type, claim_uid, asset_uid)

claim_type:
  virtual_fund_target

claim_uid:
  virtual_fund_uid for virtual-fund targets
```

These claims are not custody. They are virtual-fund exposure lines carved from
the account. After they are calculated, the direct account sleeve is whatever
signed exposure remains:

```text
direct_sleeve[asset_uid] =
  signed_account_holding[asset_uid]
  - sum(virtual_allocation[virtual_fund_uid, asset_uid])
```

All vectors are signed:

```text
requested_signed_quantity > 0  long exposure
requested_signed_quantity < 0  short exposure
requested_abs_quantity = abs(requested_signed_quantity)
```

## Allocation Policy Model

`allocation_policy` must be an explicit typed object. It should not be a loose
set of flags:

```text
AllocationPolicy
  mode: "proportional_attribution" | "strict_feasible"
  quantity_tolerance: Decimal | float
  valuation_tolerance: Decimal | float
  residual_policy: "leave_as_account_residual"
  leverage_policy: "attribute_without_borrow" | "reject"
  shortage_policy: "proportional_target_gap" | "fail"
  stale_valuation_policy: "reject" | "allow_latest"
  stale_weight_policy: "reject" | "allow_latest"
  rounding_policy: "none" | future named policy
  idempotency_mode: "replace_same_allocation_run" | "fail_if_existing"
```

The default policy is:

```text
mode = "proportional_attribution"
residual_policy = "leave_as_account_residual"
leverage_policy = "attribute_without_borrow"
shortage_policy = "proportional_target_gap"
stale_valuation_policy = "reject"
stale_weight_policy = "reject"
rounding_policy = "none"
idempotency_mode = "replace_same_allocation_run"
```

`strict_feasible` is the validation mode. It sets `shortage_policy = "fail"` and
requires every claim to be fully filled before apply.

## Strict Feasible Policy

The strict validation policy is:

```text
strict_feasible
```

For every `asset_uid`:

```text
sum(abs(virtual_target[virtual_fund_uid, asset_uid]))
<= gross_source_capacity + tolerance
```

If this condition fails for any pool, the planner returns a failed allocation
plan with deficits and must not publish `VirtualFundHoldingsStorage` rows.

If the condition passes:

1. Allocate each portfolio-expanded demand to its corresponding virtual fund.
2. Compute the direct account sleeve as the residual balance.
3. Report direct target gap and any residual diagnostics.

This policy avoids silently changing target weights, borrowing assets,
selling residual assets, or allocating holdings without a documented policy.

`strict_feasible` is useful as a validation policy and for tests that require an
exact target fit. It is not sufficient as the practical attribution policy for
live accounts, because real accounts can be underfunded or drifted. In those
cases the virtual fund should carry a target gap instead of making the planner
unusable.

## Proportional Attribution Policy

The default practical non-trading attribution policy is:

```text
proportional_attribution
```

This policy never invents assets, trades, borrows, or changes custody. It
allocates the virtual-fund target matrix first and computes the direct account
sleeve as the residual balance. Direct account targets are not part of the fill
ratio. They are only used to measure how far the balancing direct sleeve is
from the desired direct exposure.

This must be implemented as vectorized pandas operations over `asset_uid` and
`virtual_fund_uid`, not line-by-line source matching. The planner should build
grouped holding vectors, grouped target matrices, per-asset scale factors, and
then merge/broadcast those vectors back to result frames.

For each `asset_uid`:

```text
H = signed_account_holding
  = sum(quantity * direction)

C = gross_source_capacity
  = sum(abs(quantity))

V*_f = desired signed virtual-fund target for virtual fund f

G = sum(abs(V*_f) for every virtual fund f)

scale = min(1, C / G) if G > 0 else 0

V_f = V*_f * scale

D = H - sum(V_f)

virtual_fund_gap_f = V*_f - V_f
direct_gap = direct_target - D

balance invariant:
  D + sum(V_f) = H
```

Example:

```text
direct target requested = 7 BTC
virtual fund requested  = 5 BTC
available               = 10 BTC

H = 10
C = 10
G = abs(5) = 5
scale = 1

virtual fund holding           = 5 BTC
direct account sleeve          = H - 5 = 5 BTC

direct target gap = 7 - 5 = 2 BTC
virtual fund gap  = 5 - 5 = 0 BTC
```

Opposite-signed direct and virtual targets do not net and do not share a fill
ratio, because the direct target is not a fill competitor:

```text
direct target requested = -7 BTC
virtual fund requested  =  5 BTC
available               = 10 BTC

H = 10
C = 10
G = abs(5) = 5
scale = 1

virtual fund holding           = 5 BTC
direct account sleeve          = H - 5 = 5 BTC

direct target gap = -7 - 5 = -12 BTC
virtual fund gap  =  5 - 5 =   0 BTC
```

The policy must never compute `abs(-7 + 5)` or otherwise let opposite-signed
direct and virtual targets offset each other. It must also never include direct
targets in the virtual-fund fill denominator. The direct sleeve is always the
balancing residual.

The result must be reported as account-virtual holding lines:

```text
claim_type
claim_uid
asset_uid
asset_identifier
requested_direction
requested_signed_quantity
allocated_signed_quantity
target_gap_signed_quantity
requested_abs_quantity
allocated_abs_quantity
target_gap_abs_quantity
requested_notional
allocated_notional
target_gap_notional
scale
```

For `claim_type = virtual_fund_target`, `allocated_abs_quantity` is the quantity
published into `VirtualFundHoldingsStorage`, and `requested_direction`
determines the storage `direction`.
`VirtualFundHoldingsStorage.allocation_strategy` records the allocation policy
mode used to create the row as first-class storage state, not as nested
`extra_details` metadata.
`target_gap_signed_quantity` remains diagnostic tracking error for that virtual
fund target. For `claim_type = direct_account_residual`, no virtual-fund row is
published; the line records the account's balancing direct sleeve and target
gap.

Current `VirtualFundHoldingsStorage` is indexed by `(time_index,
virtual_fund_uid, asset_identifier)`, not by direction. If the virtual target
matrix produces both long and short rows for the same virtual fund, asset, and
time, the apply step must fail or require a storage-contract change. It must
not silently net opposite target directions into one published row.

## More Assets Than Needed

When the account has more of an asset than the virtual-fund allocation needs:

```text
gross_source_capacity > virtual_gross_demand
```

The extra quantity stays in the direct account sleeve through the balance
equation. It is not pushed into a virtual fund unless a future policy explicitly
says how residuals should be assigned.

The plan must report residuals:

```text
asset_uid
asset_identifier
signed_account_holding
gross_source_capacity
virtual_gross_demand
virtual_allocated_signed_quantity
direct_sleeve_signed_quantity
direct_target_signed_quantity
direct_target_gap_signed_quantity
residual_notional
```

Residuals are expected when virtual-fund target exposures consume less than the
account's holdings, when the account holds non-target assets, or when holdings
drift away from the target.

## Not Enough Assets

When virtual funds request more gross exposure for an asset than the account can
support, behavior depends on `allocation_policy`:

```text
gross_source_capacity < virtual_gross_demand
```

Under `strict_feasible`, the plan fails and reports deficits. Under
`proportional_attribution`, the plan remains usable: each virtual-fund claim
receives its proportional share of the available gross source capacity, and the
target gap is carried as tracking error on that virtual-fund claim. The direct
account sleeve is still computed afterward as the residual balance.

The plan must report target gaps:

```text
asset_uid
asset_identifier
gross_source_capacity
virtual_gross_demand
scale
target_gap_abs_quantity
target_gap_notional
affected_virtual_funds
virtual_fund_holding_lines
direct_sleeve_line
```

The service must not create virtual-fund holdings for assets the account does
not hold unless a future execution workflow explicitly models trades, cash,
borrow, or financing.

Optional future policies may include:

```text
priority_waterfall
allow_cash_purchase
allow_short_borrow
reject_short_virtual_exposure
```

Those policies must be named and documented before implementation. They must
return tracking-error diagnostics because they intentionally deviate from the
target allocation.

## Multiple Virtual Funds

One account target allocation can contain multiple portfolio target rows. Each
portfolio target row should resolve or create a virtual fund for the account and
target portfolio.

Demand is a matrix:

```text
virtual_fund_uid x asset_uid x asset_identifier -> requested_signed_quantity
```

When multiple virtual funds require the same asset pool, `strict_feasible`
requires aggregate feasibility:

```text
sum(abs(requested_signed_quantity) for all virtual funds)
<= gross_source_capacity
```

If strict feasibility passes, each virtual fund receives its full requested
quantity. If it fails under `strict_feasible`, the plan fails and reports which
funds are competing for the constrained asset. Under `proportional_attribution`,
each competing virtual fund receives its proportional share of the constrained
gross source capacity, and each fund line carries its own target gap. The direct
account sleeve is the balancing residual after those virtual-fund allocations.

## VirtualFund Identity Gap

The current virtual-fund table records:

```text
VirtualFundTable
  unique_identifier
  account_uid
  target_portfolio_uid
```

That is enough to publish holdings, but it does not make the account allocation
mandate explicit. The canonical virtual-fund creation path should create or
reuse one virtual fund per:

```text
account_target_allocation_uid
target_portfolio_uid
```

So the follow-up schema migration should add:

```text
VirtualFundTable.account_target_allocation_uid
  -> AccountTargetAllocationTable.uid
```

and enforce uniqueness on `(account_target_allocation_uid, target_portfolio_uid)`.
No allocation-run table is required.

## Package Boundary

This ADR changes the intended ownership of virtual funds.

`VirtualFundTable`, `VirtualFundHoldingsSetTable`, and
`VirtualFundHoldingsStorage` should become core `msm` account-allocation
models. A virtual fund is an account allocation view over real account holdings;
it is not portfolio construction state. Keeping it in core lets account
allocation, direct sleeve residuals, target gaps, and virtual-fund holdings be
implemented in one account-domain service without making core `msm` import
`msm_portfolios`.

Target core locations:

```text
src/msm/models/accounts/virtual_funds.py
  VirtualFundTable
  VirtualFundHoldingsSetTable

src/msm/data_nodes/accounts/virtual_funds/storage.py
  VirtualFundHoldingsStorage

src/msm/services/accounts/account_virtual_allocations.py
  plan_account_virtual_fund_allocations(...)
  apply_account_virtual_fund_allocation_plan(...)
```

Today `src/msm/services/accounts.py` is a module, not a package. Implementing
the target service path requires converting it into:

```text
src/msm/services/accounts/__init__.py
src/msm/services/accounts/core.py
src/msm/services/accounts/account_virtual_allocations.py
```

That import-layout change should be done directly, without compatibility helper
modules, unless a later compatibility ADR explicitly requires them.

`msm_portfolios` remains the portfolio construction engine. It should continue
to own portfolio calculation DataNodes, portfolio weights, signals, rebalance
strategies, contributed price/signal nodes, and portfolio examples. The account
allocation planner may use a portfolio-target expansion boundary supplied by
`msm_portfolios`, but the vector allocation equation and virtual-fund apply
step belong to core `msm`.

The dependency direction remains:

```text
msm_portfolios -> msm
```

Core `msm` must not import `msm_portfolios`. If the planner needs portfolio
weights, it should receive or call an explicit portfolio target expansion
protocol that can be implemented by `msm_portfolios` at the workflow boundary.

This supersedes the part of ADR 0019 that placed virtual funds under
`msm_portfolios`. `msm_portfolios` should be treated as the construction engine;
virtual funds should be treated as core account allocation state.

## Service Shape

The service is split into a canonical planner and an apply step.

Planner:

```python
plan_account_virtual_fund_allocations(
    *,
    position_set_uid,
    valuation_time,
    valuation_asset_uid,
    holdings_selection_policy,
    valuation_resolver,
    allocation_policy,
) -> AccountVirtualFundAllocationPlan
```

These are the service inputs. Raw holdings, raw target demands, account UID,
holdings-set UID, account NAV, repository context, scan limits, and custom
input resolvers are not public planner inputs. The service resolves them from
`position_set_uid`.

The service resolves:

```text
PositionSetTable.uid
  -> AccountTargetAllocationTable.uid
  -> AccountHoldingsSetTable(account_uid, valuation_time)
  -> AccountHoldingsStorage rows
  -> TargetPositionsStorage rows
  -> AssetTable identity rows
  -> portfolio-target expansion boundary
  -> valuation resolver
```

The public planner resolves the account/target/asset relationship graph from
the required inputs. Portfolio target rows are expanded internally through the
registered portfolio index and `PortfolioWeightsStorage` at `valuation_time`.

The planner performs no writes. It returns:

```text
AccountVirtualFundAllocationPlan
  status = feasible | attributed_with_target_gap | infeasible
  account_uid
  source_account_holdings_set_uid
  account_nav
  source_holdings
  direct_target_demands
  virtual_fund_demands
  account_virtual_holding_lines
  virtual_fund_allocations
  residuals
  target_gaps
  deficits
  diagnostics
```

Apply step:

```python
apply_account_virtual_fund_allocation_plan(
    plan,
    *,
    data_node=None,
    run=False,
)
```

The apply step may:

1. Create or reuse `VirtualFundTable` rows.
2. Create holdings-set records.
3. Build a `VirtualFundHoldingsStorage` frame.
4. Attach and optionally publish through `VirtualFundHoldings`.

The existing `VirtualFund.allocate_from_account_holdings_set(...)` should remain
a low-level explicit-allocation helper. It must not be the policy engine.

## Validation Rules

The planner must validate:

- `position_set_uid` resolves through `AccountTargetAllocationTable` to exactly
  one account;
- `holdings_selection_policy` resolves exactly one `AccountHoldingsSetTable`
  row for the account derived from `position_set_uid`;
- exactly one exposure field is present on each target row;
- portfolio target rows do not use `single_asset_quantity`;
- every portfolio target resolves to portfolio weights at `valuation_time`;
- every held and target asset resolves to an `AssetTable` row;
- every held and target asset has valuation output;
- source holdings quantities are positive and direction is `1` or `-1`;
- requested signed target quantities are non-zero;
- `proportional_attribution` computes per-asset scale factors from virtual-fund
  gross demand only and never includes direct account targets in the fill
  denominator;
- published virtual-fund storage quantities are positive and derive from
  `abs(allocated_signed_quantity)` with storage `direction` carrying the
  requested target sign;
- strict feasibility holds before apply only when
  `allocation_policy.mode == "strict_feasible"`;
- no virtual-fund output allocation exceeds the per-asset gross source
  capacity after scaling;
- direct account sleeve plus virtual-fund allocations reconciles to signed
  account holdings for every asset;
- plan output is deterministic for the same inputs.

## Edge Cases

### Target Exposures Sum To Less Than 100%

The unallocated portion remains residual account holdings. It is reported but
not assigned to a virtual fund.

### Target Exposures Sum To More Than 100%

This implies leverage in the desired target allocation. Under
`proportional_attribution`, the planner may still attribute only available real
holdings and report the resulting target gaps. Actual borrowing or financing is
not allowed unless an explicit execution policy exists.

### Account Holds Non-Target Assets

Non-target holdings remain residual. They do not fund portfolio targets unless
an execution/rebalance workflow converts them.

### Portfolio Needs Asset Not Held By Account

Under `proportional_attribution`, allocate zero for that claim and report a full
target gap. Under `strict_feasible`, fail with a deficit. Do not synthesize a
holding or assume the account can trade into the asset.

### Portfolio Weight Is Negative

The desired virtual-fund allocation is short. Under `proportional_attribution`,
the claim can receive a negative virtual holding as long as the virtual-fund
gross demand fits inside the asset's gross source capacity after scaling. For
example, if the account has `10 BTC` and the short virtual-fund target is
`-5 BTC`, the planner can attribute `-5 BTC` to that virtual fund. The direct
account sleeve becomes `+15 BTC` so that `+15 + (-5) = +10`. Under
`strict_feasible`, the absolute virtual-fund desired quantity must fit inside
the available gross source capacity unless a later policy rejects short virtual
exposures explicitly.

### Account Has Short Holdings But Long Target

For attribution, virtual-fund target claims are signed rows in the virtual
target matrix. The direct account target does not compete with them. The direct
account sleeve is the residual balance against the signed account holding.
Execution or borrow workflows may later decide how to trade or finance the
mismatch; the allocation planner only attributes available virtual-fund
capacity and reports target gaps.

### Missing Portfolio Weights

Reject by default. Latest-available weights can be used only under an explicit
valuation policy.

### Missing Valuations Or Conversion

Reject by default. The planner cannot compute NAV, target notionals, or target
quantities without valuation output in `valuation_asset_uid`.

### Rounding And Lot Sizes

The initial planner should use exact floating quantities and expose optional
rounding as a later policy. Rounding must report residuals and tracking error.

### Existing Virtual-Fund Allocations

The planner must account for existing allocation rows from the same source
holdings set. Replacing the same allocation run should be idempotent; creating
a second allocation over the same source and target must not double allocate
the same source holdings.

## Documentation Requirements

The implementation is incomplete unless the following documents are updated:

- `docs/ADR/0019-msm-portfolios-package-boundary.md`
- `docs/knowledge/msm/accounts/virtual_funds.md`
- `docs/knowledge/msm_portfolios/portfolios/index.md`
- `docs/knowledge/msm/accounts/index.md`
- account and virtual-fund examples under `examples/msm/` and
  `examples/msm_portfolios/`
- packaged skills for account, portfolio, and valuation-resolver workflows

The virtual-fund docs must show that allocated quantities come from the planner,
not from arbitrary hardcoded example payloads.

## Implementation Plan

- [x] Define the pure allocation-plan data models:
      source holdings, target demand, expanded portfolio demand,
      account-virtual holding lines, residuals, target gaps, deficits, and
      diagnostics.
- [x] Define the allocation policy model with `proportional_attribution` as the
      default and `strict_feasible` as a validation mode.
- [x] Add implementation support for account holdings, target position sets,
      deterministic portfolio expansion, and valuation behind the canonical
      planner inputs.
- [x] Move virtual-fund identity and holdings storage into core `msm` account
      modules:
      `src/msm/models/accounts/virtual_funds.py` and
      `src/msm/data_nodes/accounts/virtual_funds/storage.py`.
- [x] Convert `src/msm/services/accounts.py` into a package and place the
      planner in `src/msm/services/accounts/account_virtual_allocations.py`.
- [x] Keep `msm_portfolios` as the portfolio construction engine and expose a
      portfolio-target expansion boundary instead of making core `msm` import
      portfolio construction modules.
- [x] Implement `plan_account_virtual_fund_allocations(...)` with no writes.
- [x] Add deterministic virtual-fund identity rules for
      account/portfolio/target-allocation combinations through
      `virtual_fund_unique_identifier_for_target(...)`.
- [ ] Add `VirtualFundTable.account_target_allocation_uid` and uniqueness on
      `(account_target_allocation_uid, target_portfolio_uid)` in the next schema
      migration. No allocation-run table is required.
- [x] Implement the apply step that converts a feasible plan into
      `VirtualFundHoldingsStorage` rows.
- [x] Keep `VirtualFund.allocate_from_account_holdings_set(...)` as a low-level
      explicit allocation publisher, not the policy engine.
- [x] Add focused planner tests for exact fit, excess/direct residual,
      insufficient holdings, multiple funds competing for the same asset,
      opposite-signed direct targets, and short virtual-fund targets.
- [x] Add resolver-level tests for deterministic virtual-fund identity,
      portfolio target expansion, notional-to-quantity valuation conversion,
      missing portfolio expansion, and planner execution through an input
      resolver.
- [x] Add a virtual-fund allocation example that starts with account holdings
      and account target allocation, runs the planner, displays the plan, and
      only then applies it as an extension of the full account workflow.
- [x] Update account, portfolio, and virtual-fund documentation with the
      documented planner flow and edge-case behavior.

## Non-Goals

- Do not execute trades.
- Do not rebalance account holdings.
- Do not infer cash purchases.
- Do not borrow assets for short allocation.
- Do not allocate residual holdings without an explicit policy.
- Do not make portfolio construction create virtual funds.
- Do not make virtual funds canonical custody.
