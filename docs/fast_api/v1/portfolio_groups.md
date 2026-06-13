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
GET /api/v1/portfolio-group/?response_format=frontend_list&search=&limit=50&offset=0
```

Returns `PaginatedResponse[PortfolioGroup]`.

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

Bulk delete accepts explicit group `uids` and/or `unique_identifiers`.

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

## Relationship Lists

```text
GET /api/v1/portfolio-group/{uid}/portfolios/
GET /api/v1/portfolio-group/by-portfolio/{portfolio_uid}/
```

The first route returns all portfolios in a group. The second route returns all
groups containing one portfolio. `DELETE
/api/v1/portfolio-group/{uid}/portfolios/{portfolio_uid}/` removes only the
membership row.
