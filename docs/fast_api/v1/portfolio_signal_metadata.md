# Portfolio Signal Metadata Routes

The `apps/v1` portfolio-signal routes expose `SignalMetadataTable` rows and
their associated `SignalWeightsStorage` cleanup operations.

These routes manage signal metadata only. They do not run signal updaters or
portfolio calculation jobs.

`signal_description` is a plain-text or Markdown string. Do not send HTML tags;
the API does not define HTML rendering semantics for signal descriptions.

## Runtime Sources

- Signal metadata uses `msm_portfolios.api.market_metadata.SignalMetadata`.
- Create and update payloads use
  `SignalMetadataCreate` and `SignalMetadataUpdate`.
- Historical signal weights use
  `msm_portfolios.time_index.signals.storage.SignalWeightsStorage`.

`SignalWeightsStorage.signal_uid` references `SignalMetadataTable.signal_uid`.
Deleting a signal metadata row therefore deletes the signal's weight rows and
then the metadata row, in one transaction.

A signal's weights are published to Markets' own `SignalWeightsStorage`
through the `signal-weights` row operations
([Row Operations](rows.md#published-series)); Markets reads no other
application's table. `SignalMetadata.managed_by` names the principal that
created the row, recorded by Markets from the acting identity of the create
call; no create or update payload sets it. Only that
principal deletes the signal or its weights; any other caller, and every caller
while the row has no manager, gets `403`.

## List Portfolio Signals

```text
GET /api/v1/portfolio-signal/?search=&signal_uid=&limit=25&offset=0
```

Returns `command-center.resource_collection@v1` and exposes
`GET /api/v1/portfolio-signal/discovery/`:

```json
{
  "items": [
    {
      "uid": "signal-metadata-uid",
      "signal_uid": "canonical-signal-key",
      "signal_description": "Human-readable signal description"
    }
  ],
  "pageInfo": {
    "pageIndex": 0,
    "pageSize": 25,
    "totalItems": 1,
    "hasNextPage": false,
    "hasPreviousPage": false
  }
}
```

`search` is a contains filter over `signal_uid`. `signal_uid` is an exact
filter.

## Get Portfolio Signal

```text
GET /api/v1/portfolio-signal/{uid}/
```

Returns one `SignalMetadata` row by metadata row `uid`:

```json
{
  "uid": "signal-metadata-uid",
  "signal_uid": "canonical-signal-key",
  "signal_description": "Human-readable signal description"
}
```

Missing rows return 404.

## Create Portfolio Signal

```text
POST /api/v1/portfolio-signal/
```

Request:

```json
{
  "signal_uid": "canonical-signal-key",
  "signal_description": "Human-readable signal description"
}
```

Response: `SignalMetadata`.

## Update Portfolio Signal

```text
PATCH /api/v1/portfolio-signal/{uid}/
```

Request:

```json
{
  "signal_description": "Updated human-readable signal description"
}
```

Response: `SignalMetadata`.

`signal_uid` is immutable because `SignalWeightsStorage` rows reference it.

## Delete Portfolio Signal Weights

```text
DELETE /api/v1/portfolio-signal/{uid}/weights/?weights_date=2026-06-10T10:30:00Z
```

Deletes historical `SignalWeightsStorage` rows for the metadata row's
`signal_uid` through the storage table's
`TimeIndexMetaTable.delete_after_date(...)` API.

When `weights_date` is omitted, all weight rows for the signal are deleted.
When `weights_date` is provided, rows at or after that timestamp are deleted.
The API never calls `delete_after_date(None)` without a `signal_uid` dimension
scope. Only the signal's manager may delete its weights (`403` otherwise).

Response:

```json
{
  "detail": "Signal weights deleted.",
  "signal_metadata_uid": "signal-metadata-uid",
  "signal_uid": "canonical-signal-key",
  "weights_date": "2026-06-10T10:30:00Z",
  "deleted_count": 12
}
```

## Delete Portfolio Signal

```text
DELETE /api/v1/portfolio-signal/{uid}/
```

Deletes one signal metadata row and all its `SignalWeightsStorage` rows in
one transaction, or nothing. `SignalMetadata.end(signal_uid)` and
`msm_portfolios.recipes.end_signal` do the same by `signal_uid`.
`SignalMetadata.end_many(signal_uids)` and `msm_portfolios.recipes.end_signals`
end several signals in one row operation and one transaction
([issue 126](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/126)):
they answer `ended`, each as `end` answers it, and `failed`, each signal that is
missing, that the caller does not manage or that a portfolio names, with the
reason. A refused signal never stops the others.

Response:

```json
{
  "detail": "Signal metadata deleted.",
  "signal_metadata_uid": "signal-metadata-uid",
  "signal_uid": "canonical-signal-key",
  "deleted_count": 1,
  "deleted_weights_count": 12
}
```

Missing metadata rows return 404. A caller that does not manage the signal gets
403. A portfolio that still names the signal refuses the delete with 409, and
nothing is deleted.
