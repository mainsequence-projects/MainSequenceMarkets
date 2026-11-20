# Remote Row Operations

These routes serve `msm.client`'s remote backend
([ADR 0047](../../ADR/0047-markets-api-application-boundary.md), decision 2).
An application that selects the remote backend runs `msm.api` row class methods
here instead of holding MetaTables grants on `mainsequence.markets`. See
[Client](../../knowledge/msm/client/index.md) for the application side.

## Describe Row Operations

```text
GET /api/v1/rows/
```

Lists every row resource (`asset`, `account`, `portfolio`, `currency-spot`,
`index`, `calendar` ...), its row class and each operation with its name,
whether it writes and its Python signature.

## Run A Row Operation

```text
POST /api/v1/rows/{resource}/{operation}/
```

Request:

```json
{"arguments": {"unique_identifier": "ACME", "asset_type": "equity"}}
```

Response:

```json
{"result": {"uid": "...", "unique_identifier": "ACME", "asset_type": "equity"}}
```

`operation` is a public class method of the row class registered as
`resource`, for example `upsert`, `get_by_uid`, `get_many_by_unique_identifier`,
`filter`, `list_related_meta_tables` or `CurrencySpot.upsert`'s `upsert`.
`arguments` are its named arguments; a Pydantic payload is sent as an object
with only the fields that were set. The route runs the method on this
deployment's runtime backend and returns its result as JSON. There is no
generic query: `filter` and `count` accept equality, `<field>_contains`,
`<field>__in` and `<field>__gte`/`__gt`/`__lte`/`__lt` filters on the row
model's own fields only.

Writes (`create`, `upsert`, `update`, `delete`, `add`, `bulk_delete`,
`add_portfolio`, `remove_portfolio`, `replace_memberships`, `create_batch`,
`create_from_pandas_calendar`, `link_many`, `reconcile_dataset_availability`, `upsert_many`,
`add_many`, `create_index_curve_selection`, `get_or_create_currency`,
`upsert_index_curve_selection`, `publish`, `delete_after`, `assign_manager`, `end`,
`activate_definition`, `retire_definition`) run through `registry_write`, which
records who made them and binds the acting manager (see
[Published series](#published-series)).
A row class that defines its own `delete` runs it like any other operation:
`account` (the cascading account delete, with `bulk_delete`, ADR 0050),
`signal-metadata` (the signal's weights and its row, in one transaction) and the
composites (`curve`, `pricing-market-data-set`, the binding resources). Any other
table row class's `delete` runs the resource's service delete with its preflight
checks and exists only for `asset`, `asset-category`, `calendar`, `index` and
`portfolio-group`; every other resource answers `501`
"`<Class>.delete` is not offered remotely." The account-history resources
(`account-holdings-set`, `account-target-allocation`, `position-set`,
`virtual-fund`, `virtual-fund-holdings-set`) answer `501` with the text their
row class raises under the runtime backend too: an account's history is kept
for as long as the account exists, and only the account delete removes it
([ADR 0049](../../ADR/0049-portfolio-lifecycle-and-account-history.md)). So
does `portfolio`: a portfolio is deleted with its seven datasets only through
[`DELETE /api/v1/portfolio/{uid}/`](portfolio.md#delete-portfolio) and
`POST /api/v1/portfolio/bulk-delete/`.

The calendar resources are `calendar`, `calendar-session-rule` and
`calendar-exception`
([ADR 0055](../../ADR/0055-calendars-as-rules-and-exceptions.md)).
`Calendar.sessions`, `Calendar.dates` and `Calendar.is_business_day` compute
their answer from the calendar's rules and exceptions. A date outside the
calendar's `valid_from` to `valid_to` range answers `400` with `error_type`
`CalendarRangeError`. A `calendar-exception` written here is stored with
`source="user"`.

The resources include the `msm_portfolios.api` metadata rows
(`signal-metadata`, `portfolio-metadata`, `rebalance-strategy-metadata`), the
three published series (`signal-weights`, `portfolio-weights`,
`portfolio-values`) and the `msm_pricing.api` composites (`curve`, `curve-building-details`,
`index-convention-details`, `pricing-market-data-set`,
`pricing-market-data-set-binding`, `pricing-market-data-set-curve-binding`,
`asset-current-pricing-details`, `asset-pricing-details`).

| Status | Meaning | `error_type` |
|---|---|---|
| 400 | Invalid arguments | `ValueError`, `TypeError` |
| 403 | The operation refused the acting identity | `PermissionError` or a subclass |
| 404 | Unknown resource or operation, or the row was not found | `LookupError` |
| 409 | The operation conflicted with existing rows | the conflict class name |
| 500 | MetaTables rejected a statement this deployment compiled as invalid; a retry fails the same way | `InvalidStatementError` |
| 501 | The operation is not offered remotely | `NotImplementedError` |
| 502 | An API this deployment calls, normally MetaTables, refused the call (permissions, a missing table, a conflict) | `UpstreamApiError` |
| 503 | That API failed or could not be reached; the operation may be tried again | `UpstreamApiError` |

The `500`, `502` and `503` answers are the same on every route of the API, not only
on these; see [Upstream errors](index.md#upstream-errors). `msm.client` raises
`MarketsInvalidStatementError` for the `500` and `MarketsUpstreamError` for the
`502` and `503`.

`upsert_many` takes a list of any length. A long list is written in several
statements, each its own transaction, so a failure part of the way leaves the
earlier rows written; sending the same list again finishes the write
([Bulk upserts of any length](../../knowledge/msm/repositories/index.md#bulk-upserts-of-any-length)).

## Published Series

Signal weights, portfolio weights and portfolio values are stored once, in
Markets' own tables, and an application publishes them here
([ADR 0060](../../ADR/0060-producers-publish-markets-reads-only-its-own-tables.md)).
Markets reads no application's table: no operation takes a table uid.

| Resource | Row class | Key |
|---|---|---|
| `signal-weights` | `SignalWeightsSeries` | `SignalMetadata.signal_uid` |
| `portfolio-weights` | `PortfolioWeightsSeries` | `Portfolio.unique_identifier` |
| `portfolio-values` | `PortfolioValuesSeries` | `Portfolio.unique_identifier` |

| Operation | Writes | Arguments | Result |
|---|---|---|---|
| `publish` | yes | `key`, `rows` | Rows written and skipped; the key's first time, last time and row count |
| `window` | no | `keys`, `start`, `end`, `columns`, `assets` (weights only), `limit` (default 5,000, at most 9,000), `offset`, `newest_first` | One page of rows; `next_offset` when the page was full |
| `last` | no | `keys`, `at`, `by` (`key` or `asset`, weights only), `inclusive`, `assets` (weights only) | The last rows at or before `at`, at most 9,000 |
| `bounds` | no | `keys` | First time, last time and row count per key |
| `assets` | no | `key` | Every asset the key has had a row for |
| `delete_after` | yes | `key`, `time` | Rows deleted after `time` |

`publish` writes one key's rows in one transaction, at most 10,000 rows per
call. A row equal to the stored one is skipped; a different row for a stored
time (and asset) answers `400` and nothing is written, so sending the same rows
again writes nothing. On `signal-weights` times must carry a timezone, weights
must be finite numbers, assets must be registered (`404` otherwise), an asset
the signal held and an observation leaves out is written at `0`, and an
observation at or before the signal's last stored time is refused. On the two
portfolio series, rows at or after the portfolio's retirement are refused.

`Portfolio` and `SignalMetadata` rows carry `managed_by`, recorded by this API
from the acting identity of the create call: `branch:<uid>` for a workload of
a code repository branch, `user:<uid>` for a person or any other identity. A
payload that sends `managed_by` answers `400`. `publish` and `delete_after` on
a series, the delete of a `signal-metadata` row (`delete`, or `end` by
`signal_uid`) and the portfolio delete answer `403` for any caller but the
row's manager, and for every caller while the row has no manager.
`assign_manager` (`uid`, `managed_by`) on `portfolio` and `signal-metadata`
sets the manager; only an Organization admin may call it, any other caller
gets `403`.
