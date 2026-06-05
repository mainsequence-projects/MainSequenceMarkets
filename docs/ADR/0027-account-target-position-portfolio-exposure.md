# 0027. Account Target Position Portfolio Exposure

## Status

Accepted - planned

This ADR defines the target architecture for account target-position rows that
can reference either direct assets or constructed portfolios. It is not yet
implemented.

## Context

`AccountModelPortfolioTable`, `AccountTargetPortfolioTable`, and
`PositionSetTable` are core account concepts. They define:

```text
AccountModelPortfolioTable
  reusable model mandate

AccountTargetPortfolioTable
  account -> account model mandate

PositionSetTable
  concrete UTC-stamped target snapshot for one account target portfolio
```

The actual target exposure rows currently live in `TargetPositionsStorage` and
are asset-only:

```text
TargetPositionsStorage
  time_index
  position_set_uid -> PositionSetTable.uid
  asset_identifier -> AssetTable.unique_identifier
  weight_notional_exposure
  constant_notional_exposure
  single_asset_quantity
```

That shape is too narrow for account mandates that allocate to a constructed
portfolio sleeve, for example:

```text
60% direct BTC
40% PortfolioTable(uid=...)
```

Creating a synthetic `AssetTable` row for a portfolio is wrong because a
portfolio is not a traded/custodied asset. Using the optional portfolio
`IndexTable` linkage is also wrong because an index is a publication or
benchmark representation, not the target exposure object.

ADR 0019 keeps portfolio construction models in `msm_portfolios`.
`PortfolioTable` is owned by `msm_portfolios`, while core account registry rows
remain in `msm`.

## Decision

Target-position exposure will support exactly two target kinds:

```text
asset
portfolio
```

Do not introduce a generic normalized `PositionTargetTable`. We do not expect
additional target kinds, and a normalized target table would add lookup
indirection without improving the current domain model.

Do not create portfolio assets. Do not use portfolio indices as account target
position identities.

Instead, expand the target-position storage contract to carry an explicit target
kind and canonical target UID:

```text
TargetPositionsStorage
  time_index
  position_set_uid      FK -> PositionSetTable.uid
  target_type           "asset" | "portfolio"
  target_uid            canonical UID for row identity
  asset_uid             nullable FK -> AssetTable.uid
  portfolio_uid         nullable FK -> PortfolioTable.uid
  weight_notional_exposure
  constant_notional_exposure
  single_asset_quantity
  metadata_json
```

The DataNode storage index is:

```text
(time_index, position_set_uid, target_type, target_uid)
```

`target_uid` is intentionally duplicated from the concrete FK column so storage
identity is non-null and stable for both target kinds. The concrete FK columns
preserve relational integrity.

The row must satisfy exactly one of these shapes:

```text
target_type = "asset"
  target_uid = asset_uid
  asset_uid is not null
  portfolio_uid is null

target_type = "portfolio"
  target_uid = portfolio_uid
  portfolio_uid is not null
  asset_uid is null
```

## Package Boundary

The expanded storage table references `PortfolioTable`, which lives in
`msm_portfolios`. Core `msm` must not import `msm_portfolios`.

Therefore:

- `AccountTable`, `AccountGroupTable`, `AccountModelPortfolioTable`,
  `AccountTargetPortfolioTable`, `AccountHoldingsSetTable`, and
  `PositionSetTable` remain in core `msm`.
- The expanded portfolio-aware target-position storage and its DataNode belong
  to `msm_portfolios`.
- Core `msm` should not own a storage table that has a foreign key to
  `PortfolioTable`.

This amends ADR 0019 by clarifying that account target-position registry rows
remain core, but portfolio-aware target-position exposure storage is a
portfolio-package integration.

## Relationship Diagram

```text
                         Account Mandate Registry

+-------------------------------+
| AccountModelPortfolioTable    |
| MetaTable: AccountModelPortf. |
|-------------------------------|
| uid PK                        |
| model_portfolio_name unique   |
+---------------+---------------+
                |
                | account_model_portfolio_uid
                v
+-------------------------------+        +-------------------------------+
| AccountTargetPortfolioTable   |        | AccountTable                  |
| MetaTable: AccountTargetPortf.|        | MetaTable: Account            |
|-------------------------------|        |-------------------------------|
| uid PK                        |        | uid PK                        |
| account_uid FK ---------------+------->| account identity              |
| account_model_portfolio_uid   |        +-------------------------------+
+---------------+---------------+
                |
                | account_target_portfolio_uid
                v
+-------------------------------+
| PositionSetTable              |
| MetaTable: PositionSet        |
|-------------------------------|
| uid PK                        |
| position_set_time UTC         |
+---------------+---------------+
                |
                | position_set_uid
                v
+-------------------------------+
| TargetPositionsStorage        |
| PlatformTimeIndexMetaTable    |
| owner: msm_portfolios         |
|-------------------------------|
| time_index                    |
| position_set_uid FK           |
| target_type                   |
| target_uid                    |
| asset_uid nullable FK         |
| portfolio_uid nullable FK     |
| exposure columns              |
+----------+----------------+---+
           |                |
           | asset_uid      | portfolio_uid
           v                v
+-------------------+    +-------------------+
| AssetTable        |    | PortfolioTable    |
| MetaTable: Asset  |    | MetaTable:        |
| owner: msm        |    | Portfolio         |
+-------------------+    | owner:            |
                         | msm_portfolios    |
                         +-------------------+
```

## Exposure Semantics

Asset target rows represent direct target exposure to a specific `AssetTable`
row.

Portfolio target rows represent target exposure to a constructed
`PortfolioTable` row. They are not custody holdings. They must be expanded into
underlying asset exposure only when a downstream workflow needs asset-level
orders, risk, or account holdings simulation.

```text
TargetPositionsStorage row
  target_type = "portfolio"
  portfolio_uid = P
        |
        v
resolve PortfolioTable(P)
        |
        v
read portfolio weights / latest portfolio composition
        |
        v
expand to asset-level exposure for execution, risk, or reporting
```

The target-position table stores mandate intent. It does not store expanded
portfolio constituents.

## Documentation Update Requirements

Implementing this architecture must update the documentation at the same time
as the schema, service, and example changes. The implementation is incomplete if
the docs still describe target positions as asset-only or still show
`asset_identifier` as the target-position storage identity.

Required documentation updates:

- `docs/knowledge/msm/accounts/index.md` must explain that core account rows own
  account identity, account groups, model mandates, account target portfolios,
  and position sets, while portfolio-aware target exposure storage lives in
  `msm_portfolios`.
- `docs/knowledge/msm/accounts/index.md` must replace the asset-only target
  position diagrams with diagrams showing `target_type`, `target_uid`,
  `asset_uid`, and `portfolio_uid`.
- `docs/knowledge/msm_portfolios/portfolios/index.md` must explain how
  `PortfolioTable.uid` can be referenced by account target-position exposure
  rows and how portfolio target rows are expanded into asset-level exposure only
  when downstream workflows request it.
- The account workflow documentation and tutorial pages under `docs/tutorial/`
  must show an example target set containing one direct asset target and one
  portfolio target.
- The relevant packaged agent skills must be updated so future coding agents do
  not recreate the old `asset_identifier` target-position contract:
  `.agents/skills/ms_markets/accounts/account_workflow/SKILL.md` and the
  portfolio workflow skill under `.agents/skills/ms_markets/`.
- Examples must be updated with the documentation, not after it. The example
  should be the executable form of the documented relationship diagram.

## Non-Goals

- Do not create `AssetTable` rows for portfolios.
- Do not use `IndexTable` or `portfolio_index_uid` as the target-position
  identity.
- Do not introduce a generic `PositionTargetTable`.
- Do not support arbitrary future target kinds in this ADR.
- Do not keep backward-compatible `asset_identifier` write paths when the
  storage contract is migrated.
- Do not move core account registry MetaTables into `msm_portfolios`.

## Implementation Tasks

- [ ] Move portfolio-aware target-position storage ownership to
      `msm_portfolios` while keeping account registry MetaTables in core `msm`.
- [ ] Replace `TargetPositionsStorage.asset_identifier` with `target_type`,
      `target_uid`, `asset_uid`, and `portfolio_uid`.
- [ ] Change `TargetPositionsStorage.__index_names__` to
      `["time_index", "position_set_uid", "target_type", "target_uid"]`.
- [ ] Add SQL checks enforcing exactly one concrete target FK and consistency
      between `target_type`, `target_uid`, `asset_uid`, and `portfolio_uid`.
- [ ] Add indexes for `asset_uid`, `portfolio_uid`, and
      `(position_set_uid, target_type, target_uid)`.
- [ ] Update target-position frame builders to accept exactly one of
      `asset_uid` or `portfolio_uid` and to populate `target_type` and
      `target_uid`.
- [ ] Update target-position validation to reject `asset_identifier` payloads
      and any row with both or neither target FK.
- [ ] Update account target-position snapshot services to return target
      metadata for both asset and portfolio rows.
- [ ] Add a portfolio-target expansion service that resolves `portfolio_uid` to
      current portfolio weights only when a downstream workflow explicitly asks
      for asset-level exposure.
- [ ] Update account and portfolio examples to publish target rows containing
      both a direct asset target and a portfolio target.
- [ ] Update account docs, portfolio docs, tutorial docs, examples, packaged
      skills, and ASCII diagrams according to the Documentation Update
      Requirements section.
- [ ] Generate the Alembic migration under the active namespace version graph.
- [ ] Add tests for asset target rows, portfolio target rows, invalid mixed
      target rows, storage index names, service payload validation, and
      portfolio expansion behavior.

## Success Criteria

This ADR is complete only when:

- target-position rows can reference either `AssetTable.uid` or
  `PortfolioTable.uid`;
- target-position storage no longer uses `asset_identifier`;
- storage identity is `(time_index, position_set_uid, target_type, target_uid)`;
- SQL and service validation enforce exactly one concrete target reference;
- core `msm` does not import `msm_portfolios`;
- examples demonstrate one direct asset target and one portfolio target;
- docs make clear that portfolio target rows are mandate exposure, not custody
  holdings and not portfolio indices;
- account docs, portfolio docs, tutorial docs, examples, packaged skills, and
  diagrams no longer describe target positions as asset-only or based on
  `asset_identifier`.
