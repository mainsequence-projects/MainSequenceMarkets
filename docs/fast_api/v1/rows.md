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
`create_from_pandas_calendar`, `reconcile_dataset_availability`, `upsert_many`,
`add_many`, `create_index_curve_selection`, `upsert_index_curve_selection`,
`publish`, `register`, `register_signal`, `unregister`, `unregister_signal`, `reconcile`, `activate_definition`,
`retire_definition`) run through `registry_write`, which records who made them.
A row class that defines its own `delete` runs it like any other operation:
`account` (the cascading account delete, with `bulk_delete`, ADR 0050) and the
composites (`curve`, `pricing-market-data-set`, the binding resources). Any other
table row class's `delete` runs the resource's service delete with its preflight
checks and exists only for `asset`, `asset-category`, `calendar`, `index`,
`portfolio` and `portfolio-group`; every other resource answers `501`
"`<Class>.delete` is not offered remotely." The account-history resources
(`account-holdings-set`, `account-target-allocation`, `position-set`,
`virtual-fund`, `virtual-fund-holdings-set`) answer `501` with the text their
row class raises under the runtime backend too: an account's history is kept
for as long as the account exists, and only the account delete removes it
([ADR 0049](../../ADR/0049-portfolio-lifecycle-and-account-history.md)).

The calendar resources are `calendar`, `calendar-session-rule` and
`calendar-exception`
([ADR 0055](../../ADR/0055-calendars-as-rules-and-exceptions.md)).
`Calendar.sessions`, `Calendar.dates` and `Calendar.is_business_day` compute
their answer from the calendar's rules and exceptions. A date outside the
calendar's `valid_from` to `valid_to` range answers `400` with `error_type`
`CalendarRangeError`. A `calendar-exception` written here is stored with
`source="user"`.

The resources include the `msm_portfolios.api` metadata rows
(`signal-metadata`, `portfolio-metadata`, `rebalance-strategy-metadata`) and
the `msm_pricing.api` composites (`curve`, `curve-building-details`,
`index-convention-details`, `pricing-market-data-set`,
`pricing-market-data-set-binding`, `pricing-market-data-set-curve-binding`,
`asset-current-pricing-details`, `asset-pricing-details`).

| Status | Meaning | `error_type` |
|---|---|---|
| 400 | Invalid arguments | `ValueError`, `TypeError` |
| 403 | The operation refused the acting identity | `PermissionError` or a subclass |
| 404 | Unknown resource or operation, or the row was not found | `LookupError` |
| 409 | The operation conflicted with existing rows | the conflict class name |
| 501 | The operation is not offered remotely | `NotImplementedError` |
