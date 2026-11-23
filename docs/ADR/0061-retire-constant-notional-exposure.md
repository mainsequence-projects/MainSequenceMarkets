# 0061. Retire The Constant Notional Exposure

## Status

Accepted (2026-11-23). The decisions marked (owner) were made by the owner on 2026-11-19:
`constant_notional_exposure` is retired with every reference to it, and no code refuses the
retired name by itself. The owner approved the rest, as a plan, on 2026-11-23. Implemented
on `development` for 5.3.0.

- It amends decision 1 of [ADR 0054](0054-account-exposure-and-sized-fund-targets.md): a
  portfolio row states `weight_notional_exposure` only.
- It amends [ADR 0027](0027-account-target-position-portfolio-exposure.md) and
  [ADR 0029](0029-account-holdings-virtual-fund-allocation-policy.md), which list the amount
  among the exposure columns.
- It changes the `owner_size` default and the worked example of the proposed
  [Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md).

## Context

ADR 0054 lets an account state its exposure to a portfolio in one of two ways:
`weight_notional_exposure`, a share of the account's NAV, or `constant_notional_exposure`, an
amount. An asset row could state an amount too.

The provider sizes every exposure into units at every sync, with that sync's prices (ADR 0054,
decision 3). So an amount is imposed again at every sync, and the fund never keeps its own
gains or losses. In the guides' example, fund B is 300,000: half MSFT at 400 (375 shares) and
half JNJ at 150 (1,000 shares).

- **MSFT rises 10%.** Fund B is worth 315,000. The next sync sizes it back to 300,000, which is
  341 MSFT. The 34 shares it gives up, about 15,000, leave the fund for the account.
- **MSFT falls 10%.** Fund B is worth 285,000. The next sync sizes it back to 300,000, which is
  417 MSFT. The account's cash buys the 42 missing shares, about 15,000, to refill the fund.

Nobody who asks for "300,000 in this portfolio" means that, and the fund's value no longer
says how the portfolio did. No example, test or guide used the amount for anything else, such
as an unfunded overlay sized in notional.

What the owner wants instead is a locked amount: money given to the portfolio once, which then
grows or shrinks with the fund's own gains and losses. That needs cash the fund owns, fund
holdings that carry over between syncs, and a record of money moving in and out. None of
these exists yet.

## Decision

### 1. The amount is retired (owner)

- `TargetPositionsStorage.constant_notional_exposure` is dropped, together with its API
  fields, its client, service and repository code, and the "Notional" column of "Accounts
  targeting the portfolio".
- A portfolio row states `weight_notional_exposure`. An asset row states
  `weight_notional_exposure` or `single_asset_quantity`.
- The check `ck_target_positions_single_exposure` keeps its name and requires exactly one of
  those two fields.

### 2. Nothing replaces it here

The locked amount is a design of its own. `weight_notional_exposure` is unchanged. Whether a
share of the account stays a rule applied again at every sync belongs to that design.

### 3. A row accepts only its own fields (owner)

Nothing checks for the retired name. A write that still sends it is refused like any other
field a row doesn't have:

- The API's request models already forbid unknown fields: the route answers 422, and
  `MarketsClient` raises a validation error before it sends anything.
- In-process writes get the same rule. `validate_target_position_payload` refuses any key that
  is not a `TargetPositionsStorage` column, taking the columns from the storage model. Every
  in-process write passes through it: `build_target_positions_frame`,
  `validate_target_positions_frame` and the `TargetPositions` updater. Before, they dropped or
  passed on a key they did not know. The rule replaces the check that refused
  `asset_identifier` by name.

### 4. Revision 0036 drops the column

Revision 0036 drops the check, drops the column, and creates the check again with the new SQL
under the same physical name. MetaTables builds that name from the table and the constraint
name, not from the SQL.

A row that still holds an amount gets no check of its own either. Once the column is gone,
such a row holds neither field, so the recreated check refuses it and the upgrade fails.
MetaTables' migration environment runs the upgrade in one transaction, so on PostgreSQL the
failure leaves the database as it was. Nothing is deleted: account target history is never
rewritten. With no real portfolios yet, no deployment is expected to hold such a row.

The downgrade adds the column back, nullable, with the three-field check.

## Consequences

- It breaks anyone who writes account targets, so it ships as 5.3.0.
- An account whose target states an amount must state a share instead, before the upgrade.
- An in-process caller that passes a key which is not a column now fails.
- Responses no longer carry the field. Their models ignore unknown fields, so a client of
  either version reads the other's responses.
- In the guides, fund B becomes 30% of the 1,000,000 account. Its sized units (375 MSFT,
  1,000 JNJ) don't change.
