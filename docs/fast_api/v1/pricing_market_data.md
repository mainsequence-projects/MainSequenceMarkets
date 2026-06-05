# Pricing Market Data Routes

The pricing market-data route group is exposed under:

```text
/api/v1/pricing/market_data/
```

The FastAPI layer is a resolver only. Row contracts and CRUD operations come
from `msm_pricing.api`.

## Discoverability

```text
GET /api/v1/pricing/market_data/
```

Response:

```json
{
  "resource": "pricing_market_data",
  "description": "Manage pricing market-data sets and concept bindings.",
  "resources": [
    {
      "key": "sets",
      "model": "PricingMarketDataSet",
      "list_url": "/api/v1/pricing/market_data/sets/",
      "create_url": "/api/v1/pricing/market_data/sets/",
      "upsert_url": "/api/v1/pricing/market_data/sets/upsert/"
    },
    {
      "key": "bindings",
      "model": "PricingMarketDataSetBinding",
      "list_url": "/api/v1/pricing/market_data/bindings/",
      "create_url": "/api/v1/pricing/market_data/bindings/",
      "upsert_url": "/api/v1/pricing/market_data/bindings/upsert/"
    }
  ]
}
```

## Data Sets

```text
GET /api/v1/pricing/market_data/sets/?limit=25&offset=0&status=ACTIVE&set_key=default
```

Response uses the shared limit-offset pagination envelope:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "7f958bbf-44cc-4cb9-ad19-b41b5aa28d60",
      "set_key": "default",
      "display_name": "Default pricing market data",
      "description": null,
      "status": "ACTIVE",
      "metadata_json": null
    }
  ]
}
```

```text
GET /api/v1/pricing/market_data/sets/{uid}/
GET /api/v1/pricing/market_data/sets/by-key/{set_key}/
```

Response:

```json
{
  "uid": "7f958bbf-44cc-4cb9-ad19-b41b5aa28d60",
  "set_key": "default",
  "display_name": "Default pricing market data",
  "description": null,
  "status": "ACTIVE",
  "metadata_json": null
}
```

```text
POST /api/v1/pricing/market_data/sets/
POST /api/v1/pricing/market_data/sets/upsert/
PATCH /api/v1/pricing/market_data/sets/{uid}/
```

Request bodies use the corresponding `msm_pricing.api` contracts:

- `PricingMarketDataSetCreate`
- `PricingMarketDataSetUpsert`
- `PricingMarketDataSetUpdate`

Responses return `PricingMarketDataSet`.

```text
DELETE /api/v1/pricing/market_data/sets/{uid}/
```

Response:

```json
{
  "detail": "Deleted pricing market-data set.",
  "uid": "7f958bbf-44cc-4cb9-ad19-b41b5aa28d60",
  "deleted_count": 1
}
```

Deleting a set relies on backend cascade behavior for related binding rows.

## Bindings

```text
GET /api/v1/pricing/market_data/bindings/?limit=25&offset=0&market_data_set_uid=...&concept_key=discount_curves
GET /api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/?limit=25&offset=0
```

Response:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "6b8fd8e4-6748-423c-b9fb-fad522d6f150",
      "market_data_set_uid": "7f958bbf-44cc-4cb9-ad19-b41b5aa28d60",
      "concept_key": "discount_curves",
      "data_node_uid": "5f4d0bb8-36f0-44fc-a9fc-f42dd3ce7f2d",
      "storage_table_identifier": "DiscountCurvesStorage",
      "source": "example",
      "metadata_json": null
    }
  ]
}
```

```text
GET /api/v1/pricing/market_data/bindings/{uid}/
```

Response:

```json
{
  "uid": "6b8fd8e4-6748-423c-b9fb-fad522d6f150",
  "market_data_set_uid": "7f958bbf-44cc-4cb9-ad19-b41b5aa28d60",
  "concept_key": "discount_curves",
  "data_node_uid": "5f4d0bb8-36f0-44fc-a9fc-f42dd3ce7f2d",
  "storage_table_identifier": "DiscountCurvesStorage",
  "source": "example",
  "metadata_json": null
}
```

```text
GET /api/v1/pricing/market_data/bindings/resolve/?market_data_set=default&concept_key=discount_curves
```

Response:

```json
{
  "market_data_set": "default",
  "concept_key": "discount_curves",
  "data_node_uid": "5f4d0bb8-36f0-44fc-a9fc-f42dd3ce7f2d"
}
```

```text
POST /api/v1/pricing/market_data/bindings/
POST /api/v1/pricing/market_data/bindings/upsert/
PATCH /api/v1/pricing/market_data/bindings/{uid}/
```

Request bodies use the corresponding `msm_pricing.api` contracts:

- `PricingMarketDataSetBindingCreate`
- `PricingMarketDataSetBindingUpsert`
- `PricingMarketDataSetBindingUpdate`

Responses return `PricingMarketDataSetBinding`.

```text
DELETE /api/v1/pricing/market_data/bindings/{uid}/
```

Response:

```json
{
  "detail": "Deleted pricing market-data binding.",
  "uid": "6b8fd8e4-6748-423c-b9fb-fad522d6f150",
  "deleted_count": 1
}
```

## Pagination

All list endpoints in this route group use the shared FastAPI v1
`PaginatedResponse[T]` contract:

```json
{
  "count": 123,
  "next": "http://testserver/api/v1/pricing/market_data/sets/?limit=25&offset=25",
  "previous": null,
  "results": []
}
```

`count` is the total number of rows matching the exact filters. `limit` and
`offset` are request query parameters and are not included in the response body.
