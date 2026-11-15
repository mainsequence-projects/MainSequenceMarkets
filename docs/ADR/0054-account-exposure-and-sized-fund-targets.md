# 0054. Account Exposure To Portfolios And Sized Fund Targets At The Sync

## Status

Accepted (2026-11-15). The decisions marked (owner) were made by the owner on 2026-11-15.
Implemented on `development` for 3.7.0; see "Implementation Notes".

- It supersedes [ADR 0052](0052-account-targets-in-units.md). That ADR replaced the account's
  exposure to a portfolio with unit rows per asset. A portfolio has weights, not units, so a
  user could no longer state an exposure to a portfolio at all.
- It restores the account target of
  [ADR 0027](0027-account-target-position-portfolio-exposure.md) as it was before ADR 0052.
- It amends [ADR 0053](0053-virtual-fund-allocation-routes-and-described-policies.md): the
  allocation takes the sized target units in its request and records its lines, for funds and
  for the account's direct part (see "Amendment To ADR 0053").
- It answers
  [issue 71](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/71): a
  virtual fund is created when its exposure is written.

## Context

ADR 0052 was released in 3.6.0. It merged two different things into one row:

- **The exposure.** What the user asks for: a share of the account's NAV, or a notional
  amount, in one `Portfolio`. It names no asset and no quantity.
- **The sized target.** What that exposure means in units per asset at one moment. Computing
  it needs prices, so it is the provider's work.

ADR 0052 removed the first and stored the second in its place. Three things followed:

- **No way to state an exposure.** `weight_notional_exposure` and
  `constant_notional_exposure` were removed from `TargetPositionsStorage`, and the target write
  refuses them.
- **Existing targets were deleted.** Migration 0024 deletes every `PositionSet` and its target
  rows. It ran on every deployment that upgraded to 3.6.0.
- **A requested fund did not exist.** A `VirtualFund` row was written only by an allocation
  that assigned it at least one unit, and an allocation that assigned nothing was refused
  (`nothing_to_apply`). An account that had just been given an exposure, and held none of the
  fund's assets yet, could not be allocated.

What stays true from ADR 0052 and ADR 0053: ms-markets takes no price and computes no NAV. The
provider owns the prices and the sizing rules. The allocation policy works in units.

## Decision

### 1. The account target states exposure (owner)

A row of `TargetPositionsStorage` with `target_type="portfolio"` is the account's exposure to
one `Portfolio`:

- `target_uid` and `portfolio_uid` name the `Portfolio`; `asset_uid` is null.
- Exactly one of `weight_notional_exposure` (a share of the account's NAV) and
  `constant_notional_exposure` (an amount) is set.
- There is one row per portfolio in a `PositionSet`.

`TargetPositionsStorage` returns to its shape before ADR 0052, including the rows with
`target_type="asset"`. The unit columns ADR 0052 added to it (`quantity`, `direction`) and the
required `asset_uid` on portfolio rows are removed.

### 2. Writing an exposure creates the fund (owner)

The target write already carries everything a fund needs: the account and the `Portfolio`. For
each portfolio row of the `PositionSet`, `add_account_target_positions` creates the
`VirtualFund` of that account and portfolio if it does not exist, in the same transaction as
the target rows.

A fund then exists from the moment it is requested. It has no holdings until the first sync.

### 3. The sync sizes and allocates in one call (owner)

A sync is one holdings snapshot of the account at time `T`, allocated to the account's funds.
The provider:

1. publishes the account's holdings at `T` (`AccountHoldingsSet`, `AccountHoldingsStorage`);
2. sizes each fund: turns its exposure into target units per asset, with its own prices and
   rules;
3. calls the allocation with those target units.

ms-markets assigns the account's holdings to the funds with the policy of ADR 0053. It reads
no price. The request names the `PositionSet`, the holdings time and the sized targets:

```json
{
  "position_set_uid": "…",
  "valuation_time": "2026-11-16T21:00:00Z",
  "sized_targets": [
    {
      "target_type": "portfolio",
      "target_uid": "<portfolio A>",
      "positions": [
        {"asset_uid": "<AAPL>", "quantity": 1200, "direction": 1},
        {"asset_uid": "<MSFT>", "quantity": 400, "direction": 1}
      ]
    }
  ]
}
```

- Every portfolio row of the `PositionSet` must be sized. An empty `positions` list is a fund
  sized to nothing.
- An asset row stated as a share or an amount must be sized too, with `target_type: "asset"`
  and at most one position in its own asset. An asset row stated as `single_asset_quantity`
  is already in units and is not sized.
- A target that is not in the `PositionSet` is refused.
- A `quantity` is positive; `direction` is `1` or `-1`.
- Any mismatch answers 400 `invalid_sized_targets` and lists every problem.

### 4. The sync records its lines: target and assigned, for every owner (owner)

The sync and its deltas are kept, because they are what a rebalance trades. A delta belongs
to the sync and to an owner of a target. The owner is a virtual fund, or the account itself
for a direct asset target and for what no fund takes. So the record is general: one row per
sync, owner and asset.

`AccountAllocationLinesStorage` is new:

| Column | Meaning |
| --- | --- |
| `time_index`, `holdings_set_uid` | The sync: the time and the `AccountHoldingsSet` that was allocated. One allocation per holdings snapshot |
| `owner_type`, `owner_uid` | Who the line belongs to: `fund` with the `VirtualFund` uid, or `direct` with the account's uid for what the account holds outside its funds |
| `asset_identifier` | The asset |
| `target_quantity`, `target_direction` | The owner's sized target, in units |
| `assigned_quantity`, `assigned_direction` | What the owner was assigned of the account's holdings |
| `allocation_strategy`, `extra_details` | The policy id; its version, the `PositionSet` and the plan digest |

The delta is not a column. It is read from the row:

```text
delta = target_quantity * target_direction - assigned_quantity * assigned_direction
```

- **Fund lines and direct lines are stored the same way.** A direct asset target sized as a
  share or an amount has its line too, so its delta is kept like a fund's.
- **A line with nothing assigned is stored.** A fund the account holds nothing of has its
  lines with `assigned_quantity = 0`, so its whole target reads as the delta.
- **`VirtualFundHoldingsStorage` is unchanged.** It holds what each fund was assigned, and
  nothing else. A fund that was assigned nothing has no row there.
- **One `VirtualFundHoldingsSet` per fund** is still written at every sync, pointing at the
  `AccountHoldingsSet` of `T`.

`GET /api/v1/account/{account_uid}/virtual-fund-allocations/` answers the lines of one sync,
the latest by default, with `target`, `assigned` and `delta` per line.

### 5. An allocation always writes (owner)

- Every fund of the `PositionSet` gets its holdings set and its lines at every sync.
- A target with no fund is recorded too: its direct lines are the whole allocation.
- `nothing_to_apply` is removed. An allocation that assigns no units is a valid allocation of
  that snapshot.
- An allocation stays account history: one per holdings snapshot. The same request again
  writes nothing; a different allocation of the same snapshot is refused.

## Worked Example

Portfolio A is 60% AAPL and 40% MSFT. Portfolio B is 50% MSFT and 50% JNJ. The account holds
AAPL 1,000, MSFT 600, JNJ 1,000 and TSLA 1,640; TSLA is in no fund. The provider's prices at
the sync are AAPL 200, MSFT 400, JNJ 150 and TSLA 250, so the account is worth 1,000,000.

**The exposure**, in `TargetPositionsStorage` under one `PositionSet`:

| `target_type` | `portfolio_uid` | `weight_notional_exposure` | `constant_notional_exposure` |
| --- | --- | --- | --- |
| portfolio | A | 0.40 | |
| portfolio | B | | 300,000 |

Writing these rows creates two `VirtualFund` rows: (account, A) and (account, B).

**The sizing**, by the provider. Fund A is 40% of 1,000,000 = 400,000. Fund B is 300,000.

| Fund | Asset | Calculation | Target units |
| --- | --- | --- | --- |
| A | AAPL | 400,000 × 60% ÷ 200 | 1,200 |
| A | MSFT | 400,000 × 40% ÷ 400 | 400 |
| B | MSFT | 300,000 × 50% ÷ 400 | 375 |
| B | JNJ | 300,000 × 50% ÷ 150 | 1,000 |

**The allocation.** The funds claim 775 MSFT against 600 held, so each gets the same fraction
of its claim (`proportional_attribution`).

**What the sync stores**, in `AccountAllocationLinesStorage`, for the holdings snapshot of `T`:

| `owner_type` | Owner | Asset | `target_quantity` | `assigned_quantity` | Delta (read) |
| --- | --- | --- | --- | --- | --- |
| fund | Fund A | AAPL | 1,200 | 1,000 | 200 |
| fund | Fund A | MSFT | 400 | 309.68 | 90.32 |
| fund | Fund B | MSFT | 375 | 290.32 | 84.68 |
| fund | Fund B | JNJ | 1,000 | 1,000 | 0 |
| direct | The account | TSLA | 0 | 1,640 | −1,640 |

`VirtualFundHoldingsStorage` holds the four assigned quantities, under one
`VirtualFundHoldingsSet` per fund.

If the account target also had an asset row for TSLA with `weight_notional_exposure = 0.05`,
the provider would size it as 1,000,000 × 5% ÷ 250 = 200 TSLA, and the direct line would be
stored as target 200, assigned 1,640, delta −1,440.

## Who Does What

| Step | Who | Needs prices |
| --- | --- | --- |
| State the exposure: a share of NAV or an amount per portfolio | The user, through the provider | No |
| Record the exposure and create the fund | ms-markets | No |
| Publish the account's holdings | The provider | No |
| Size each fund into target units | The provider | Yes |
| Assign holdings to funds; record target and assigned units per owner | ms-markets | No |
| Read the deltas and trade them | The provider | Yes |

## Amendment To ADR 0053

- **Request.** `planAccountVirtualFunds` and `allocateAccountVirtualFunds` take
  `sized_targets`. The plan still writes nothing.
- **Fund targets.** A fund's target units come from the request, not from
  `TargetPositionsStorage`. The funds themselves are the portfolio rows of the `PositionSet`.
- **Stored result.** The allocation records its lines in `AccountAllocationLinesStorage`;
  "deltas are never stored" becomes "the delta is read from the stored target and assigned
  units of each line".
- **Read.** `getAccountVirtualFundAllocation` (`GET` on the allocate path) answers the lines
  of one allocation.
- **`nothing_to_apply`.** Removed.
- **`plan_digest`.** It covers the sized targets, so an allocate call with other targets than
  the plan it names is refused (`plan_changed`).
- **Unchanged.** The policy registry, `proportional_attribution` and its arguments, the policy
  version check, the four routes, and the rule that an applied allocation is history.

## Migration

One revision after 0024:

- `TargetPositionsStorage`: restore `weight_notional_exposure`, `constant_notional_exposure`
  and `single_asset_quantity`; drop `quantity` and `direction`; make `asset_uid` nullable; put
  back the former checks and the former index.
- `AccountAllocationLinesStorage`: created.

Targets deleted by revision 0024 are not restored by a migration; they were not kept anywhere
in ms-markets.

## Decisions Taken During Implementation

These were open when the ADR was proposed. The owner has not reviewed the choices.

- **Targets written under 3.6.** Revision 0025 turns an asset row written in units into
  `single_asset_quantity`. It deletes a `PositionSet` that has a portfolio row in units, with
  its rows: units per asset cannot be turned back into a share or an amount.
- **Allocations written before this ADR.** They have no lines. Their fund holdings are kept,
  and `getAccountVirtualFundAllocation` answers no line for those snapshots.
- **Direct asset targets.** An asset row stated as a share or an amount is sized in the same
  request as the funds. Its line is stored like a fund's, with the account as its owner.
- **Version.** 3.7.0.

## Implementation Notes

- **Revision 0025** restores `TargetPositionsStorage` and creates
  `AccountAllocationLinesStorage`. The account delete removes an account's lines.
- **Target write.** `add_account_target_positions` reads the account's target allocation,
  builds each fund's key from it and creates the missing `VirtualFund` rows in the write's
  transaction. A fund is not created when the stored target allocation has another uid than
  the one the keys were built from; the next allocation creates it.
- **Allocation.** `sized_target_rows` matches the exposure rows with the request.
  `virtual_fund_holdings_from_plan` gives each fund's assigned rows, and
  `allocation_lines_from_plan` the lines. One write inserts the funds, their holdings sets,
  their holdings rows and the lines.
- **An allocated snapshot.** A snapshot has an allocation when it has lines, or a fund
  holdings set, which is all an allocation written before this ADR left.
- **Same allocation again.** The plan digest is stored on the lines. An allocation written
  before this ADR has it on its fund holdings rows.
- **Reads.** `getAccountVirtualFundAllocation` reads the lines. `holdings/by-fund/` and the
  fund holdings route are unchanged.
- **Plan speed.** The policy and the plan run in one pass over their inputs.

## Consequences

- A user can state an exposure to a portfolio again.
- A fund exists as soon as it is requested, and every sync leaves a record of each owner's
  target, what it was assigned and the difference, for funds and for direct targets.
- A provider that upgraded to 3.6 and writes unit targets must change again: write exposure
  rows, and send the units with the allocation.
- The sized targets are valid for the prices of that sync. The next sync sizes again.
- Projects that planned on ADR 0052's unit targets must be reviewed.

## Not Verified

- Revision 0025 and both writes were run on SQLite only. The PostgreSQL statements were not
  executed on PostgreSQL or TimescaleDB.
- `examples/msm/accounts/account_portfolio_full_workflow.py` needs a backend and was not run.
- Whether any backup holds the targets revision 0024 deleted.
