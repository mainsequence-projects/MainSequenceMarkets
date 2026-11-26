# Portfolio Group Routes

The `apps/v1` portfolio-group routes expose core `msm` portfolio group rows and
their many-to-many membership relationship to `PortfolioTable`.

Portfolio groups are classification metadata. They do not own portfolio
construction, weights, values, or signal generation. A portfolio can be in many
groups, and a group can contain many portfolios.

## Contracts

- Groups use `msm.api.portfolios.PortfolioGroup`.
- Membership rows use `msm.api.portfolios.PortfolioGroupMembership`.
- Portfolio rows returned by group membership routes use
  `msm.api.portfolios.Portfolio`.
- Deleting a group deletes only membership rows through database cascade; it
  does not delete portfolios.
- Deleting a portfolio deletes only its group membership rows through database
  cascade; it does not delete groups.

```text
+-----------------------------+        1..*        +-----------------------------------+
| PortfolioGroupTable         |------------------->| PortfolioGroupMembershipTable     |
|-----------------------------|                    |-----------------------------------|
| uid PK                      |                    | uid PK                            |
| unique_identifier unique    |                    | portfolio_group_uid FK cascade    |
| display_name                |                    | portfolio_uid FK cascade          |
| description                 |                    | unique(group, portfolio)          |
+-----------------------------+                    +------------------+----------------+
                                                                   |
                                                                   | *..1
                                                                   v
                                                        +-----------------------------+
                                                        | PortfolioTable              |
                                                        |-----------------------------|
                                                        | uid PK                      |
                                                        | unique_identifier unique    |
                                                        | calendar_uid FK NOT NULL    |
                                                        +-----------------------------+
```

## List Portfolio Groups

```text
GET /api/v1/portfolio-group/?search=&limit=50&offset=0
```

Returns `command-center.resource_collection@v1`. Discovery and the authorized
bulk-delete action are exposed at `GET /api/v1/portfolio-group/discovery/`.

## Create Or Upsert Group

```text
POST /api/v1/portfolio-group/
```

The route is idempotent by `unique_identifier`:

```json
{
  "unique_identifier": "core-portfolios",
  "display_name": "Core Portfolios",
  "description": "Core allocation mandates"
}
```

## Update Group

```text
PATCH /api/v1/portfolio-group/{uid}/
```

Updates mutable group fields: `display_name`, `description`, and
`metadata_json`.

## Delete Groups

```text
DELETE /api/v1/portfolio-group/{uid}/
POST /api/v1/portfolio-group/bulk-delete/
```

Bulk delete accepts the discovered `command-center.bulk_action_execution@v1`
body with an explicit UUID selection. It deletes every selected group that exists,
in one statement, and answers with each deleted group in `deleted` and each other
one, with the reason, in `failed`; a missing or refused group never stops the others
([issue 128](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/128)).

## Add Portfolio To Group

```text
POST /api/v1/portfolio-group/{uid}/portfolios/
```

The membership route accepts either a portfolio UID or portfolio unique
identifier:

```json
{
  "portfolio_uid": "portfolio-uid"
}
```

```json
{
  "portfolio_unique_identifier": "example-equal-weight-portfolio"
}
```

## Delete Memberships

```text
POST /api/v1/portfolio-group/membership/bulk-delete/
```

The body selects membership rows; it never deletes a portfolio or a group:

```json
{
  "uids": ["membership-uid"],
  "portfolio_group_uids": ["portfolio-group-uid"],
  "portfolio_uids": []
}
```

The selection is the memberships of `uids`, and those whose group is in
`portfolio_group_uids` and whose portfolio is in `portfolio_uids`; an empty filter does
not narrow the match, and with both empty only `uids` are selected. The database
resolves the selection, with no row cap, and deletes it in one statement. The answer is
the bulk-delete envelope: each deleted membership's `uid` in `deleted`, and each of
`uids` that was not deleted, with the reason, in `failed`
([issue 152](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/152)):

```json
{
  "detail": "Deleted 1 portfolio group membership. 1 could not be deleted.",
  "deleted_count": 1,
  "deleted": [{"uid": "membership-uid"}],
  "failed": [
    {"uid": "missing-uid", "detail": "Portfolio group membership missing-uid was not found."}
  ]
}
```

`deleted_count` counts only the deletes the call can confirm, and a selected uid whose
fate the call cannot tell is in `failed`, never in `deleted`:

- MetaTables returns at most 10,000 rows of one statement. Past that, the statement still
  deletes every match: `deleted_count` is MetaTables' count of them all, `deleted` lists
  the 10,000 it returned, and `detail` says so. A selected uid it did not return no longer
  exists, and the call cannot tell whether it deleted it or it never existed.
- When MetaTables does not answer the delete, the call reads what still matches the
  selection. Each membership still matching is in `failed`, with a reason that says the
  delete may still finish and the call may be retried; a selected uid that is gone is not
  found. When nothing matches any more, `deleted` stays empty, since the selection may have
  matched nothing, and each selected uid is reported as no longer existing. When the read
  fails too, the outcome of each selected uid is unknown.

## Relationship Lists

```text
GET /api/v1/portfolio-group/{uid}/portfolios/
GET /api/v1/portfolio-group/by-portfolio/{portfolio_uid}/
```

The first route returns all portfolios in a group. The second route returns all
groups containing one portfolio. Both return canonical resource collections
and expose sibling `/discovery/` routes. `DELETE
/api/v1/portfolio-group/{uid}/portfolios/{portfolio_uid}/` removes only the
membership row.
