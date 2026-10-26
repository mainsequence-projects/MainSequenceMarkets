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
generic query: `filter` accepts equality and `<field>_contains` filters on the
row model's own fields only.

Writes (`create`, `upsert`, `update`, `delete`, `add`, `bulk_delete`,
`add_portfolio`, `remove_portfolio`, `replace_memberships`, `create_batch`,
`create_from_pandas_calendar`, `reconcile_dataset_availability`) run through
`registry_write`, so the registry write policy applies to applications. `delete`
runs the resource's service delete with its preflight checks and exists only
for `asset`, `asset-category`, `calendar`, `index`, `portfolio` and
`portfolio-group`.

| Status | Meaning | `error_type` |
|---|---|---|
| 400 | Invalid arguments | `ValueError`, `TypeError` |
| 403 | The registry write policy refused this application | |
| 404 | Unknown resource or operation, or the row was not found | `LookupError` |
| 409 | The operation conflicted with existing rows | the conflict class name |
| 501 | The operation is not offered remotely | `NotImplementedError` |
| 503 | The registry write policy could not be read | |
