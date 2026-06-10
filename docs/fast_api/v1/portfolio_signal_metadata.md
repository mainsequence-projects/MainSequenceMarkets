# Portfolio Signal Metadata Routes

The `apps/v1` portfolio-signal routes expose `SignalMetadataTable` rows and
their associated `SignalWeightsStorage` cleanup operations.

These routes manage signal metadata only. They do not run signal DataNodes or
portfolio calculation jobs.

`signal_description` is a plain-text or Markdown string. Do not send HTML tags;
the API does not define HTML rendering semantics for signal descriptions.

## Runtime Sources

- Signal metadata uses `msm_portfolios.api.market_metadata.SignalMetadata`.
- Create and update payloads use
  `SignalMetadataCreate` and `SignalMetadataUpdate`.
- Historical signal weights use
  `msm_portfolios.data_nodes.signals.storage.SignalWeightsStorage`.

`SignalWeightsStorage.signal_uid` references `SignalMetadataTable.signal_uid`.
Deleting a signal metadata row therefore deletes matching signal-weight storage
rows first, in the same backend operation, before deleting the metadata row.

## List Portfolio Signals

```text
GET /api/v1/portfolio-signal/?search=&signal_uid=&limit=25&offset=0
```

Returns `PaginatedResponse[SignalMetadata]`:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "signal-metadata-uid",
      "signal_uid": "canonical-signal-key",
      "signal_description": "Human-readable signal description"
    }
  ]
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
`signal_uid`.

When `weights_date` is omitted, all weight rows for the signal are deleted.
When `weights_date` is provided, only that exact `time_index` is deleted.

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

Deletes one signal metadata row and all matching historical
`SignalWeightsStorage` rows.

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

Missing metadata rows return 404. Protected delete conflicts return 409.
