# 0052. Virtual-Fund Allocation Routes And Described Policies

## Status

Proposed (2026-11-15). This is a draft for the owner's review; nothing in it is implemented,
and no issue has been filed for it yet.

- It is written on top of [ADR 0053](0053-account-targets-in-units.md): every account target
  is in units, so an allocation needs no price, NAV or valuation from anyone.
- It amends [ADR 0029](0029-account-holdings-virtual-fund-allocation-policy.md): the policy
  model, the plan statuses, the holdings selection policy and the apply step (see "Amendment
  To ADR 0029").
- It brings back `POST /api/v1/account/{account_uid}/virtual-fund-allocations/`, which 3.5.0
  removed ([#68](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/68)),
  with a contract that values nothing.
- It builds on [ADR 0047](0047-markets-api-application-boundary.md) (the Markets API as the
  application boundary), [ADR 0049](0049-portfolio-lifecycle-and-account-history.md) (retired
  portfolios and account history) and
  [ADR 0051](0051-account-registration-in-one-transaction.md) (writes as one statement list in
  one transaction).

## Context

### What 3.5.0 left

The planner `plan_account_virtual_fund_allocations` and its apply step
`apply_account_virtual_fund_allocation_plan` remain as Python functions in
`msm.services.accounts`. Over HTTP, the Markets API only reads the result:
`GET /api/v1/account/{account_uid}/holdings/by-fund/` and the `/api/v1/virtualfund/` routes.
The 3.5.0 changelog records the gap: an application without grants on `mainsequence.markets`
has no way to allocate through the Markets API.

### Why the 3.1.0 route was removed

`POST /api/v1/account/{account_uid}/virtual-fund-allocations/` (3.1.0,
[#46](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/46)) valued the
account itself: the valuation asset at one, and every other asset at the `price_current` of
its target portfolios' latest weights row. It refused any account that held an asset outside
its target portfolios, and it chose the policy itself. With unit targets (ADR 0053) there is
nothing left to value, so the route can come back without any of that.

### The policy describes options that never run

`AllocationPolicy` has eleven fields. The planner and the apply step read only three of them:

| Field | Read |
| --- | --- |
| `mode` | Yes: the plan status and the holdings rows' `allocation_strategy` |
| `quantity_tolerance` | Yes: deficits, target gaps, and which fills the apply step writes |
| `valuation_policy` (`ValuationPolicy`) | Passed to the caller's resolver; ms-markets checks nothing in it |
| `valuation_tolerance`, `residual_policy`, `leverage_policy`, `shortage_policy`, `stale_valuation_policy`, `stale_weight_policy`, `rounding_policy`, `idempotency_mode` | Never |

`AllocationPolicy.strict_feasible()` sets `shortage_policy="fail"`, but the status depends
only on `mode`. So `AllocationPolicy(shortage_policy="fail")` with the default mode does not
fail on a shortage. `idempotency_mode="fail_if_existing"` never fails either. Nothing a
program can read says which policies exist or what each one takes.

### The apply step can leave a partial or mixed allocation

Read from the code, not reproduced:

- `VirtualFundTable` and `VirtualFundHoldingsSetTable` rows are written first.
  `VirtualFundHoldingsStorage` rows are written only when an updater is passed with
  `run=True`. Without one, a holdings set is left with no holdings.
- Only funds with a positive fill are written. Nothing reconciles an earlier apply of the
  same snapshot whose funds or assets the new plan no longer contains.
- The writes do not happen in one transaction. The 3.1.0 route wrote through
  `replace_account_virtual_fund_holdings`, a statement list run in one transaction, and 3.5.0
  removed it.
- Since 3.4.2, `VirtualFundHoldingsSet.delete` is refused: these rows are account history.

### A pattern for described models

A described-process API, such as OGC API – Processes – Part 1: Core 1.0, works like this:

- It lists each model with an id, a version and its arguments as JSON Schema 2020-12.
- The schema is generated from the same class that validates a request, so the description
  cannot drift from what runs.
- A change to an argument, a bound or a default bumps the model's version.

This ADR adopts that description model. It does not adopt the OGC paths or their execution
semantics (see "Rejected Alternatives").

## Decision

### 1. An allocation reads units only

An allocation takes two records, both in units (ADR 0053):

- the account's holdings at the snapshot (`AccountHoldingsStorage`);
- each fund's unit basket in the position set (`TargetPositionsStorage` rows of one
  portfolio).

It reads the portfolios' lifecycle for the retired check (ADR 0049), and nothing else. No
price, NAV, valuation asset, notional or portfolio weight enters the planner, the apply step
or the routes. The caller sends no numbers at all.

### 2. Policies are described, versioned classes

A policy registry replaces the `AllocationPolicy` dataclass. Each entry has:

- an `id`, a `version` (semantic versioning), a `title` and a `description`;
- an `Arguments` class, a Pydantic model with `extra="forbid"` whose fields carry a title, a
  description, bounds and a default.

The first two entries:

| Id | Version | Behaviour | Arguments |
| --- | --- | --- | --- |
| `proportional_attribution` | 1.0.0 | Claims on an asset larger than the holding are scaled down. The plan stays `feasible`, and the shortfall is reported as deficits and gaps | `quantity_tolerance` |
| `strict_feasible` | 1.0.0 | Any deficit makes the plan `infeasible`, and it is never applied | `quantity_tolerance` |

`quantity_tolerance` is a number with a default of `1e-9` and bounds of 0 to 1 (the bounds
are a proposal).

- **Generated, never hand-written.** The JSON Schema 2020-12 of each argument, and one object
  schema over all of them, are generated from `Arguments`. Each schema declares its dialect,
  inlines its references, and leaves an optional value non-nullable.
- **One class validates.** The HTTP routes and the Python planner validate a request's
  arguments with the same class, so the description cannot drift from what runs.
- **Versions.** A change to an argument, a bound, a default or a behaviour bumps the policy's
  version. A request names the version it was built against; any other version answers 409.
- **New policies.** A new policy is a new registry entry. The catalog lists it without any
  other change.
- **Two statuses.** A plan's status answers one question only: can it be applied? It is
  `feasible` or `infeasible`. Whether every claim was filled is a separate fact: it is true
  exactly when `deficits` is empty, and each line's gap shows what its fund is missing.
  ADR 0029's third status, `attributed_with_target_gap`, is removed. It only repeated that
  `deficits` was not empty.

### 3. Which records an allocation uses

- **The target** is the `PositionSet` the caller names, used as it is.
- **The snapshot** is the account's `AccountHoldingsSet` at exactly `valuation_time`, as
  ADR 0029 resolves it. The caller names the time, never a holdings-set uid.
- **Order in time.** A `PositionSet` written after `valuation_time` is refused, as today.
- **A fund claim** is one row of a fund's basket: a portfolio, an asset, a quantity and a
  direction. The portfolio and the asset identify it, so no separate key is needed.
- **A direct target** is an asset target row. It never competes with fund claims; it is only
  measured against what the funds leave.
- **Holdings outside the targets** are not refused. They stay in the direct account sleeve.

### 4. The routes

All the routes of the allocation surface:

| Method and path | Operation id | Writes | Status |
| --- | --- | --- | --- |
| `GET /api/v1/account/virtual-fund-allocation-policies/` | `listVirtualFundAllocationPolicies` | No | New |
| `GET /api/v1/account/virtual-fund-allocation-policies/{policy_id}/` | `getVirtualFundAllocationPolicy` | No | New |
| `POST /api/v1/account/{account_uid}/virtual-fund-allocations/plan/` | `planAccountVirtualFunds` | No | New |
| `POST /api/v1/account/{account_uid}/virtual-fund-allocations/` | `allocateAccountVirtualFunds` | Yes | Brought back with a new contract (removed in 3.5.0) |
| `GET /api/v1/account/{account_uid}/holdings/by-fund/` | `getAccountHoldingsByFund` | No | Unchanged |
| `GET /api/v1/virtualfund/...` | Existing | No | Unchanged |

The two policy routes are declared before the `/{account_uid}/` routes, as `discovery/` and
`target-allocation/targets/` already are.

#### 4.1 `GET /api/v1/account/virtual-fund-allocation-policies/`

This route lists every policy: its `id`, `version`, `title`, `description`, and a `self` link
to its description. It contains no account data.

#### 4.2 `GET /api/v1/account/virtual-fund-allocation-policies/{policy_id}/`

This route describes one policy:

```json
{
  "id": "strict_feasible",
  "version": "1.0.0",
  "title": "Strict feasible",
  "description": "Any asset whose fund claims exceed the holding makes the plan infeasible; an infeasible plan is never applied.",
  "arguments": {
    "quantity_tolerance": {
      "title": "Quantity tolerance",
      "description": "Quantities within this tolerance count as zero for deficits, gaps and fills.",
      "required": false,
      "schema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "default": 1e-9
      }
    }
  },
  "arguments_schema": { "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "...": "..." }
}
```

`arguments_schema` is the object a form renders and a request's `policy.arguments` is
validated against. Unknown ids answer 404.

#### 4.3 `POST /api/v1/account/{account_uid}/virtual-fund-allocations/plan/`

This route runs the planner and writes nothing.

```json
{
  "position_set_uid": "<uid>",
  "valuation_time": "2026-11-14T21:00:00Z",
  "policy": { "id": "proportional_attribution", "version": "1.0.0", "arguments": { "quantity_tolerance": 1e-9 } }
}
```

The answer is the plan:

- `account_uid`, `holdings_set_uid`, `position_set_uid` and `valuation_time`;
- the `policy` as validated, with its defaults filled in;
- `status`: `feasible` or `infeasible` (decision 2);
- `funds`: one per fund, with its identifier and portfolio;
- `allocations`: one line per fund claim, with its request, fill, gap and scale;
- `residuals`: one per asset, with the holding, the funds' total claim, the direct sleeve
  and the direct target;
- `deficits`: one per asset the account is short of;
- `apply_blockers`: what would stop the allocate route but not the plan. Today that is a
  portfolio retired at or before the snapshot (ADR 0049);
- `plan_digest` (decision 5).

Every quantity is in the asset's own unit.

#### 4.4 `POST /api/v1/account/{account_uid}/virtual-fund-allocations/`

The body is the plan request plus an optional `plan_digest`. The route plans again from the
same inputs and then applies. It never accepts a plan from the client.

- **Digest check.** With `plan_digest`, a recomputed plan with a different digest answers 409
  `plan_changed`, and nothing is written. Without it, the route plans and applies in one call.
- **Refusals.** An `infeasible` plan answers 409 `plan_infeasible`, and a retired portfolio
  answers 409 `portfolio_retired`.
- **The answer** is the plan with `applied`, and with each fund's `virtual_fund_uid` and
  `holdings_set_uid`.

### 5. Plan digest

`plan_digest` is `sha256:` followed by the SHA-256 of the canonical JSON of the request and
the plan's allocation lines. The same request over the same records gives the same digest. A
change to the target or the holdings between plan and allocate changes it. On apply, the
digest is stored in each holdings row's `extra_details`.

### 6. Apply is one transaction, and an applied allocation is history

- **One transaction.** Apply runs one statement list in one transaction, as in ADR 0051. It
  upserts the `VirtualFundTable` row of each fund with a fill, inserts each fund's
  `VirtualFundHoldingsSetTable` row, and inserts its `VirtualFundHoldingsStorage` rows. It
  writes no updater frame, so there is no state in which a holdings set has no holdings.
- **Same snapshot again (proposal).** If the account's funds already have holdings sets for
  this snapshot:
  - when every existing row carries this plan's digest, nothing is written and the answer
    says `already_applied`;
  - otherwise the answer is 409 `allocation_exists`, and nothing is replaced. An applied
    allocation is account history, like the rows that 3.4.2 made undeletable.

  A correction is a new holdings snapshot. This replaces `idempotency_mode` with one fixed
  rule (see "Open Decisions For The Owner").
- **Kept from today.** The fund identifier (a uuid5 of account, portfolio and target
  allocation), the holdings-set uid (a uuid5 of source snapshot, fund and time), the row key
  `(time_index, virtual_fund_uid, asset_identifier)`, the positive quantity with a
  `direction`, and the retired-portfolio refusal.
- **`allocation_strategy`** is the policy id.
- **`extra_details`** holds `policy_version`, `position_set_uid`, the fund claim's gap, the
  `scale` and the `plan_digest`.

### 7. Errors

Errors use `ApiErrorResponse`. A new detail model extends `ApiErrorDetail` with an `errors`
list, which is empty unless the code needs it.

| Case | Status | `code` |
| --- | --- | --- |
| Unknown account, position set or policy; a position set of another account; no holdings set of the account at exactly `valuation_time` | 404 | `not_found` |
| `PositionSet` written after the snapshot | 400 | `target_after_snapshot` |
| Policy arguments that break the schema | 400 | `invalid_policy_arguments`, with `errors` |
| A position set with no fund target | 400 | `no_fund_target` |
| A policy version other than the registry's | 409 | `policy_version_mismatch` |
| Apply: no fill above the tolerance | 400 | `nothing_to_apply` |
| Apply: digest differs | 409 | `plan_changed` |
| Apply: plan infeasible | 409 | `plan_infeasible` |
| Apply: a retired portfolio | 409 | `portfolio_retired` |
| Apply: a different allocation of the snapshot exists | 409 | `allocation_exists` |

The Python planner raises one exception class that carries the same `code` and `errors`,
instead of a free-text `ValueError`.

### 8. Access and audit

- **Policy routes:** open to any caller of the Markets API. They hold no account data.
- **Plan:** the same access as `getAccountHoldingsByFund`.
- **Allocate:** the same access as `addAccountHoldings`, recorded by
  `registry_write("account", "apply:account-virtual-fund-allocation")`, the action the 3.1.0
  route used.
- **Account scope:** each route checks that the position set belongs to the account in the
  path. The holdings set is the account's own, because it is resolved from that account.

### 9. The Python API and the client follow the same contract

- **Policy function.** Each policy is a function of units, with no access to storage:

  ```python
  def proportional_attribution(
      holdings: Mapping[AssetId, float],
      targets: Mapping[tuple[FundId, AssetId], float],
      *,
      quantity_tolerance: float = 1e-9,
  ) -> Allocation: ...
  ```

  `holdings` and `targets` are quantity times direction.
- **Planner:** `plan_account_virtual_fund_allocations(...)` takes `position_set_uid`,
  `valuation_time` and `policy` (id, version, arguments): the same models as the HTTP body.
- **Apply:** `apply_account_virtual_fund_allocation_plan(plan)` runs decision 6's statement
  list.
- **Client:** `MarketsClient` gains `virtual_fund_allocation_policies()`,
  `virtual_fund_allocation_policy(policy_id)`, `plan_account_virtual_funds(...)` and
  `allocate_account_virtual_funds(...)`. The last name comes back with the new contract.
- **Low-level publisher:** `VirtualFund.allocate_from_account_holdings_set` remains as it is.

### 10. What is removed

This is a breaking change, so nothing is kept for compatibility. Beyond what ADR 0053
removes (the valuation resolver, the NAV, the portfolio-target expander and the notional
fields), this ADR removes:

- `AllocationPolicy` and its fields, and `AllocationPolicy.strict_feasible()`;
- `ValuationPolicy`;
- `HoldingsSelectionPolicy`, since it has one mode, which becomes the fixed rule;
- the planner's `holdings_selection_policy` and `allocation_policy` parameters;
- the `updater`, `run` and `data_node` parameters of the apply step;
- the `attributed_with_target_gap` status and `PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP`.

Every doc, skill and example that names any of these is updated in the same change.

## Policy Specifications

Each policy is specified in two parts: first what its description route serves, then the
rules the planner follows. `strict_feasible` is specified next.

### `proportional_attribution` 1.0.0

**Title:** Proportional attribution.

**Description**, as the description route serves it:

> Every fund's claim on an asset is filled in the same proportion: the account's holding of
> the asset divided by the funds' total claims on it, capped at one. A claim the holding
> cannot cover keeps the shortfall as a gap, and the plan stays usable. What the funds do not
> take stays in the direct account sleeve. Nothing is traded, borrowed or bought.

**Arguments:**

| Argument | Type | Bounds | Default | What it controls |
| --- | --- | --- | --- | --- |
| `quantity_tolerance` | number | 0 to 1 (proposal) | `1e-9` | An absolute quantity in each asset's own units. A gap or deficit at or below it counts as zero, and a fill at or below it is not written. |

#### Terms, for each asset

| Term | Meaning |
| --- | --- |
| `H` | The signed holding: quantity times direction, from the snapshot. `AccountHoldingsStorage` stores one row per asset per snapshot. |
| `C` | The capacity: `abs(H)`. |
| `R_f` | Fund `f`'s claim: quantity times direction, from its basket row for the asset. |
| `G` | The funds' gross claim: the sum of `abs(R_f)` over every fund. |
| `s` | The scale: `min(1, C / G)` when `G > 0`. |
| `A_f` | Fund `f`'s fill: `R_f * s`. |
| `D` | The direct account sleeve: `H - sum(A_f)`. |
| `T` | The direct target: the asset target's quantity times direction, or 0 when there is none. |
| Fund gap | `R_f - A_f`. |
| Direct gap | `T - D`. |
| Deficit | `G - C`, reported when it is above the tolerance. |

For every asset, `D + sum(A_f) = H`.

#### Rules

1. **Pro rata per asset.** Every claim on one asset gets the same scale `s`. No fund takes
   priority.
2. **Assets are independent.** A shortfall on one asset changes no fill on another. A fund
   short of one asset still gets all of another, so its mix can drift from its basket.
3. **Claims count gross.** Long and short claims both use up `abs(H)`. A short claim does not
   make room for a long one (edge case 6).
4. **A fill keeps its claim's side.** This holds even when the side is opposite to the
   holding's. The direct sleeve takes the difference, and it can then be larger than the
   holding (edge cases 5 and 7).
5. **Direct targets do not compete.** They never enter `G`. They are only measured against
   the sleeve (edge case 8).
6. **Assets the account does not hold.** Here `C = 0`, so each claim gets a fill of zero, a
   gap of its full claim, and the asset's deficit is `G` (edge case 4).
7. **Holdings no fund claims** stay in the direct sleeve.
8. **No trading, borrowing, purchases or rounding.** Quantities are exact floating-point
   numbers.

#### Status

- The status is always `feasible`: a plan under this policy can always be applied.
- A shortfall is reported in the deficits and in each fund line's gap, never in the status.
- Every claim is filled exactly when the deficits list is empty.

#### What apply writes

- For each fund line with `abs(A_f)` above the tolerance, apply writes one
  `VirtualFundHoldingsStorage` row: `allocated_quantity` is `abs(A_f)`, `direction` is the
  claim's direction, and `allocation_strategy` is `proportional_attribution`.
- A fund with no such line gets no fund row and no holdings set.
- Direct lines are never written.
- A plan with no fill to write answers 400 `nothing_to_apply`.

#### The reference case

Two funds of two assets each share one asset, and the account holds one asset that is in no
fund. All figures are units.

| Asset | Held | Fund A's basket | Fund B's basket | Total claimed |
| --- | --- | --- | --- | --- |
| AAPL | 1,100 | 1,000 | | 1,000 |
| MSFT | 600 | 500 | 300 | 800 |
| JNJ | 750 | | 750 | 750 |
| TSLA | 1,100 | | | 0 |

- **AAPL (fund A only):** the holding covers the claim. A gets 1,000, and 100 stay direct.
- **MSFT (shared):** 600 held against 800 claimed, so `s` = 0.75. A gets 375 with a gap of
  125, and B gets 225 with a gap of 75. Nothing stays direct, and the deficit is 200.
- **JNJ (fund B only):** B gets all 750.
- **TSLA (no fund):** all 1,100 stay direct.

| | Holds | Gap |
| --- | --- | --- |
| Fund A | AAPL 1,000, MSFT 375 | MSFT 125 |
| Fund B | MSFT 225, JNJ 750 | MSFT 75 |
| Direct sleeve | AAPL 100, TSLA 1,100 | |

The status is `feasible`, with one deficit: MSFT 200. Apply writes four rows: fund A's AAPL
and MSFT, and fund B's MSFT and JNJ.

With 900 MSFT held instead of 600, both funds are filled in full (A 500, B 300), 100 MSFT
stay direct, and there is no deficit.

#### Edge cases

X and Y are assets, and A and B are funds. On 2026-11-15 these were reproduced on today's
planner, whose quantity engine uses the same formulas, with network access blocked. Every
status is `feasible`.

| # | Holdings | Fund claims | Fills | Direct sleeve | Deficit |
| --- | --- | --- | --- | --- | --- |
| 1 | X +120 | A +80 X, B +40 X | A +80, B +40 (`s` = 1) | X 0 | None |
| 2 | X +150 | A +80 X, B +40 X | A +80, B +40 (`s` = 1) | X +30 | None |
| 3 | X +100 | A +80 X, B +40 X | A +66.67, B +33.33 (`s` = 0.8333) | X 0 | X 20 |
| 4 | X +100, no Y | A +50 Y | A 0 Y (`s` = 0) | X +100 | Y 50 |
| 5 | X +10 | A −5 X | A −5 (`s` = 1) | X +15 | None |
| 6 | X +100 | A +80 X, B −40 X | A +66.67, B −33.33 (`s` = 0.8333) | X +66.67 | X 20 |
| 7 | X −100 | A +50 X | A +50 (`s` = 1) | X −150 | None |
| 8 | X +100, direct target X +50 | A +60 X | A +60 (`s` = 1) | X +40, direct gap +10 | None |
| 9 | X +100, Y +25 | A +80 X and +50 Y, B +40 X | A +66.67 X (`s` = 0.8333) and +25 Y (`s` = 0.5), B +33.33 X | X 0, Y 0 | X 20, Y 25 |
| 10 | X −100 | A −80 X | A −80 (`s` = 1) | X −20 | None |

#### Changes from today's planner

- Today the status is `attributed_with_target_gap` whenever a fund's gap is above the
  tolerance. Under this ADR it is `feasible` (decision 2).
- A target with no fund claim raises a `ValueError`. It becomes 400 `no_fund_target`.
- A plan with nothing to apply raises a `ValueError`. It becomes 400 `nothing_to_apply`.

#### Open questions for this policy

Both follow ADR 0029 today ("Portfolio Weight Is Negative" and "Account Has Short Holdings
But Long Target"), and both decide what version 1.0.0 means:

1. **Gross or net claims.** Should a short claim use up a long holding's capacity (rule 3)?
   Under a net reading, edge case 6 would fill A +80 and B −40 in full, with a direct sleeve
   of +60.
2. **Opposite-side fills.** Should a fund get a fill on the opposite side to the account's
   holding (rule 4)? With options this would let a fund be long a contract the account is
   short. The alternative is to fill only claims on the holding's side and leave the others
   as gaps. ADR 0029 lists that as a future policy, `reject_short_virtual_exposure`.

## Amendment To ADR 0029

This ADR replaces these parts of ADR 0029. ADR 0053 separately removes its NAV calculation,
target demand expansion and valuation resolver.

| ADR 0029 section | Replaced by |
| --- | --- |
| "Inputs": the `holdings_selection_policy` and `allocation_policy` rows | Decisions 2 and 3 |
| "Allocation Policy Model" | The policy registry (decision 2) |
| "Service Shape" | Decision 9 |
| "Service Shape": `status = feasible \| attributed_with_target_gap \| infeasible` | Decision 2: `feasible` or `infeasible` |
| "Existing Virtual-Fund Allocations" | Decision 6 |

ADR 0029's choice of the holdings snapshot by `valuation_time`, never by a raw holdings-set
uid, is kept. Its allocation formulas are unchanged:

- the per-asset scale;
- the direct sleeve as the balancing residual;
- direct targets as diagnostic intent only;
- `strict_feasible` as the validation mode.

Its 3.5.0 amendment stands for the 3.1.0 contract. The route it removed comes back with the
contract of decision 4.4, which values nothing and chooses no policy.

## Open Decisions For The Owner

1. **Re-applying a snapshot.** Proposal: an applied allocation is history (decision 6). The
   alternative is 3.1.0's behaviour, which replaced the account's fund holdings for the
   snapshot in one transaction. That rewrites rows that 3.4.2 otherwise protects.
2. **`plan_digest` on allocate.** Proposal: optional, so that one call can plan and apply.
   Making it required guarantees the caller saw what is written.
3. **The bounds of `quantity_tolerance`.** Proposal: 0 to 1.

## Not Decided Here

- Whether the Command Center adapter lists the new operations.
- Asynchronous allocation (jobs) for large accounts.
- Policies beyond the first two.

## Rejected Alternatives

### ms-markets values the account

This is 3.1.0's route. ms-markets has no prices for what an account holds, and with unit
targets an allocation needs none.

### Describe every field of today's `AllocationPolicy`

Eight of the fields never run. A description that lists them tells callers they can rely on
behaviour that does not exist.

### The OGC API – Processes routes as they are

The Markets API's routes are scoped to an account and shaped for the Command Center, and
allocation needs no jobs. This ADR takes the description model (generated JSON Schema
2020-12, one validating class, versions), not the `/processes` and `/jobs` paths.

### One route that plans or applies by a flag

3.1.0 used an `apply` flag on one route. A dry run that writes nothing and a write that is
audited have different access and different refusals, so they are two operations.

### Apply an uploaded plan

A plan built by the client could carry any quantity. The allocate route recomputes the plan
from records it reads itself.

## Consequences

- An application without grants on `mainsequence.markets` can allocate again, through the
  Markets API, and it sends no market data to do so.
- The policy description cannot drift from what runs, and a stale client gets 409 instead of
  a silent change.
- Every holdings row records the policy, its version and the digest of the plan it came from.
- A price change alone never changes an allocation.
- Breaking for Python callers: the planner's and apply step's signatures change, and the
  types listed in decision 10 are removed.

## Implementation Plan

This ADR is implemented after ADR 0053.

- [ ] Policy registry, `Arguments` classes and schema generation, with tests that every
      argument has a self-contained JSON Schema 2020-12 with a title and a description.
- [ ] Each policy as a function of units, with one test per row of its reference case and
      edge cases, and the changes it lists from today's planner.
- [ ] Planner on unit targets, with structured errors.
- [ ] Plan digest.
- [ ] One-transaction apply statement list (PostgreSQL and SQLite), with the
      already-applied and `allocation_exists` rules.
- [ ] The four routes, their wire contracts in `msm.api`, and the `MarketsClient` methods.
- [ ] Removal of the types and parameters listed in decision 10, everywhere.
- [ ] ADR 0029 amendment; the virtual-funds, account routes and client pages; the account
      workflow skill; the full workflow example; the changelog.
