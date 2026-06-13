# 0032. Portfolio Groups As Many-To-Many Classification

## Status

Proposed

## Context

`msm` has `AccountGroupTable`, where account membership is modeled as a
nullable `AccountTable.account_group_uid` foreign key. That is a one-account to
zero-or-one-group relationship.

Portfolios have a different shape. Portfolio grouping is usually
classification, not ownership. A single portfolio can naturally belong to many
useful groups:

```text
crypto portfolios
production portfolios
research portfolios
client model portfolios
equal-weight strategies
USD benchmarked portfolios
high-turnover portfolios
```

Adding `portfolio_group_uid` directly to `PortfolioTable` would force exactly
one group per portfolio. That is too restrictive for portfolio workflows and
would make later classification features harder to model.

`PortfolioTable` is already a core `msm` table. Any group relationship that
references `PortfolioTable` should also live in core `msm`, not
`msm_portfolios`, so core `msm` does not need to import the portfolio
construction package.

## Decision

Introduce portfolio groups as a many-to-many MetaTable relationship in core
`msm`.

The table design is:

```text
+----------------------------+       +------------------------------------+
| PortfolioGroupTable        | 1   * | PortfolioGroupMembershipTable      |
|----------------------------|<------|------------------------------------|
| uid PK                     |       | uid PK                             |
| unique_identifier unique   |       | portfolio_group_uid FK             |
| display_name               |       | portfolio_uid FK                   |
| description nullable       |       | unique(portfolio_group_uid,        |
| metadata_json nullable     |       |        portfolio_uid)              |
+----------------------------+       +------------------+-----------------+
                                                       |
                                                       | *   1
                                                       v
                                         +-------------+------------+
                                         | PortfolioTable           |
                                         |--------------------------|
                                         | uid PK                   |
                                         | unique_identifier unique |
                                         | calendar_uid FK          |
                                         | ...                      |
                                         +--------------------------+
```

`PortfolioGroupTable` owns the reusable group identity:

```text
uid                 UUID primary key
unique_identifier   string, unique, not null
display_name         string, not null
description          text, nullable
metadata_json        JSON, nullable
```

`PortfolioGroupMembershipTable` owns membership:

```text
uid                   UUID primary key
portfolio_group_uid   FK -> PortfolioGroupTable.uid, ondelete CASCADE
portfolio_uid         FK -> PortfolioTable.uid, ondelete CASCADE
unique(portfolio_group_uid, portfolio_uid)
index(portfolio_uid)
index(portfolio_group_uid)
```

No `portfolio_group_uid` column should be added to `PortfolioTable`.

The membership table should not carry extra role, ordering, weights, or
membership metadata in the first implementation. Add those only when a concrete
workflow needs them.

## Naming

Use the existing `PortfolioTable` style:

```text
PortfolioGroupTable
PortfolioGroupMembershipTable
```

Logical MetaTable identifiers:

```text
PortfolioGroup
PortfolioGroupMembership
```

User-facing API rows should use:

```text
msm.api.portfolios.PortfolioGroup
msm.api.portfolios.PortfolioGroupMembership
```

Portfolio group APIs should expose the normal `MarketsMetaTableRow`
create/upsert/update/delete/filter surface and add portfolio-specific
convenience helpers:

```python
PortfolioGroup.add(...)
PortfolioGroup.bulk_delete(...)
PortfolioGroup.add_portfolio(...)
PortfolioGroup.remove_portfolio(...)
PortfolioGroup.get_portfolios(...)
PortfolioGroup.get_groups_for_portfolio(...)
PortfolioGroupMembership.add(...)
PortfolioGroupMembership.bulk_delete(...)
```

`PortfolioGroup.add(...)` should be an idempotent user-facing helper backed by
the group `unique_identifier`, not a separate table concept. It may delegate to
`upsert(...)` internally. Relationship helpers should resolve by UID and, where
useful, by stable unique identifiers, but the storage contract remains FK-based
on `PortfolioGroupTable.uid` and `PortfolioTable.uid`.

## Ownership

Core `msm` owns these tables because they reference `PortfolioTable`.

Expected files:

```text
src/msm/models/portfolios/groups.py
src/msm/models/portfolios/__init__.py
src/msm/models/__init__.py
src/msm/api/portfolios.py
src/msm/repositories/portfolios.py
src/msm/services/portfolios.py
```

`msm_portfolios` may consume the relationship for portfolio construction,
documentation, examples, or filtering, but it must not own the schema.

## Delete Semantics

Deleting a portfolio group should delete only membership rows:

```text
PortfolioGroupTable delete
  -> PortfolioGroupMembershipTable rows cascade
  -> PortfolioTable rows remain
```

Deleting a portfolio should delete only its membership rows:

```text
PortfolioTable delete
  -> PortfolioGroupMembershipTable rows cascade
  -> PortfolioGroupTable rows remain
```

This keeps groups as classification metadata and avoids accidental portfolio
deletion.

## Migration Semantics

This is a MetaTable schema change. Implementation must use the SDK-managed
MetaTable migration flow.

Do not hand-author create/delete migration files or low-level backend
registration payloads. The implementation should:

1. Add SQLAlchemy MetaTable declarations.
2. Add the models to the package model graph and migration provider scope.
3. Generate/apply a new Alembic revision through the documented
   `mainsequence migrations ...` provider workflow.
4. Refresh catalog bindings through the SDK migration lifecycle.

## Consequences

Positive consequences:

- A portfolio can belong to multiple business classifications.
- Group membership can be queried independently from portfolio identity.
- Core portfolio rows remain clean and do not gain a single-group assumption.
- Deleting groups or portfolios has clear cascade behavior limited to
  membership rows.

Tradeoffs:

- Reads that need group membership require a join.
- The implementation adds one more relationship table.
- Account groups and portfolio groups will intentionally use different
  relationship shapes because their business semantics differ.

## Implementation Tasks

### Stage 1: Core MetaTables

- [x] Add `PortfolioGroupTable` under `src/msm/models/portfolios/groups.py`.
- [x] Add `PortfolioGroupMembershipTable` under the same module.
- [x] Add `__metatable_description__` and column `info` metadata for every
  mapped column.
- [x] Add unique/index constraints for group identity and membership
  uniqueness.
- [x] Add FK metadata:
  `portfolio_group_uid -> PortfolioGroupTable.uid` with `ondelete="CASCADE"`;
  `portfolio_uid -> PortfolioTable.uid` with `ondelete="CASCADE"`.
- [x] Do not add `portfolio_group_uid` to `PortfolioTable`.

### Stage 2: Model Graph And Migration Provider

- [x] Export the new tables from `msm.models.portfolios` and `msm.models`.
- [x] Add the new tables to the core `msm` SQLAlchemy model graph.
- [x] Add the new tables to the SDK-managed MetaTable migration provider scope.
- [ ] Generate a new Alembic revision through the Main Sequence migration CLI.
- [x] Do not modify old applied revision files.

### Stage 3: User-Facing API And Repositories

- [x] Add `PortfolioGroup` and `PortfolioGroupMembership` row APIs under
  `msm.api.portfolios`.
- [x] Keep the inherited `create`, `upsert`, `update`, `delete`, and `filter`
  methods available for both API row classes.
- [x] Add `PortfolioGroup.add(...)` as the preferred idempotent group creation
  helper, backed by `unique_identifier`.
- [x] Add `PortfolioGroup.bulk_delete(...)` for deleting multiple groups by UID
  or `unique_identifier`.
- [x] Add `PortfolioGroup.add_portfolio(...)` for creating one membership row.
- [x] Add `PortfolioGroup.remove_portfolio(...)` for deleting one membership
  row.
- [x] Add `PortfolioGroup.get_portfolios(...)` to return all `Portfolio` rows
  in a group.
- [x] Add `PortfolioGroup.get_groups_for_portfolio(...)` to return all
  `PortfolioGroup` rows for a portfolio.
- [x] Add `PortfolioGroupMembership.add(...)` as an idempotent membership
  helper backed by `(portfolio_group_uid, portfolio_uid)`.
- [x] Add `PortfolioGroupMembership.bulk_delete(...)` for deleting multiple
  memberships by UID or by scoped group/portfolio filters.
- [x] Add repository/service helpers for filtered group and membership reads:
  by group UID, group unique identifier, portfolio UID, and portfolio unique
  identifier.
- [x] Keep API imports under core `msm`; do not make core `msm` import
  `msm_portfolios`.

### Stage 4: FastAPI v1 Route

- [x] Add an `apps/v1` router for portfolio groups, for example
  `apps/v1/routers/portfolio_groups.py`.
- [x] Add explicit request/response schemas under
  `apps/v1/schemas/portfolio_groups.py` only for HTTP envelopes or composed
  responses that cannot be represented by core `msm.api.portfolios` rows.
- [x] Add thin route/service adapters under `apps/v1/services/portfolio_groups.py`
  that delegate business logic to `src/msm`.
- [x] Add list/filter endpoints for portfolio groups.
- [x] Add create/upsert/update/delete endpoints for portfolio groups.
- [x] Add bulk-delete endpoints for portfolio groups and memberships.
- [x] Add membership endpoints to add/remove one portfolio to/from a group.
- [x] Add relationship endpoints to list portfolios in a group and groups for a
  portfolio.
- [x] Add route documentation under `docs/fast_api/v1/portfolio_groups.md` and
  wire it into `mkdocs.yml`.
- [x] Add focused FastAPI tests under `tests/msm/fastapi/v1/`.

### Stage 5: Documentation And Examples

- [x] Update `docs/knowledge/msm_portfolios/portfolios/index.md` to describe
  portfolio group classification and the many-to-many relationship.
- [x] Update `docs/knowledge/msm/models/index.md` with the new core model graph.
- [x] Update `docs/knowledge/msm/services/index.md` if group relationship
  helpers become part of the documented service layer.
- [x] Add or update a portfolio example showing one portfolio assigned to
  multiple groups.
- [x] Update the portfolio workflow skill if group membership becomes part of
  portfolio construction examples or recommended lookup workflows.
- [x] Update the changelog when implementation lands.

### Stage 6: Tests

- [x] Add model graph tests for the two new tables.
- [x] Add FK/index contract tests for membership uniqueness and cascade intent.
- [x] Add API row tests for `PortfolioGroup` and membership helpers.
- [x] Add repository tests for group membership lookup and removal.
- [x] Add bulk-delete tests for group and membership helpers.
- [x] Add FastAPI route tests for CRUD, filters, bulk delete, and relationship
  endpoints.

## Success Criteria

The implementation is complete when:

- portfolio groups are first-class core `msm` MetaTables;
- one portfolio can belong to multiple groups;
- one group can contain multiple portfolios;
- group deletion and portfolio deletion remove only membership rows;
- examples, docs, skills, and tests reflect the many-to-many contract.
