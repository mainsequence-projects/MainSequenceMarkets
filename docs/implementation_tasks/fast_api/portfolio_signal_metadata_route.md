# Portfolio Signal Metadata Route

## Goal

Expose `SignalMetadataTable` through `apps/v1` so frontend and Command Center
clients can list, inspect, create, update, and delete canonical portfolio signal
metadata.

The FastAPI route must stay a thin resolver over reusable `src/` logic. Signal
metadata contracts must reuse `msm_portfolios.api.market_metadata` models.

## Route Shape

- `GET /api/v1/portfolio-signal/`
  - List signal metadata rows.
  - Query parameters: `search`, `signal_uid`, `limit`, `offset`.
  - Response: reusable limit-offset pagination envelope with
    `SignalMetadata` rows.
- `GET /api/v1/portfolio-signal/{uid}/`
  - Return one `SignalMetadata` row by metadata row `uid`.
- `POST /api/v1/portfolio-signal/`
  - Create a signal metadata row from `SignalMetadataCreate`.
- `PATCH /api/v1/portfolio-signal/{uid}/`
  - Update only mutable signal metadata fields from `SignalMetadataUpdate`.
  - `signal_uid` is immutable because storage rows reference it.
- `DELETE /api/v1/portfolio-signal/{uid}/`
  - Properly delete one signal metadata row.
  - Delete matching `SignalWeightsStorage` rows first, then delete the
    metadata row in the same backend operation.
  - Return deleted metadata and storage counts.
- `DELETE /api/v1/portfolio-signal/{uid}/weights/`
  - Delete only historical `SignalWeightsStorage` rows for one signal metadata
    row.
  - Optional query parameter: `weights_date` for exact timestamp deletion.

## Core Implementation Tasks

- [x] Add reusable signal metadata list/detail helpers under `src/`.
- [x] Add a core delete method that deletes `SignalWeightsStorage` rows before
      deleting `SignalMetadataTable`, mirroring the portfolio delete plus
      portfolio weights cleanup pattern.
- [x] Add a core weights-only delete method for `SignalWeightsStorage`.
- [x] Keep `signal_uid` immutable in update payloads.
- [x] Add `SignalMetadata` to the FastAPI v1 runtime model list.

## FastAPI Implementation Tasks

- [x] Add `apps/v1/schemas/portfolio_signals.py`.
- [x] Add `apps/v1/services/portfolio_signals.py`.
- [x] Add `apps/v1/routers/portfolio_signals.py`.
- [x] Register the router in `apps/v1/main.py`.
- [x] Add OpenAPI metadata and explicit `response_model` declarations for every
      route.
- [x] Add Command Center adapter operation IDs for the new public routes.

## Validation Tasks

- [x] Add route tests under `tests/msm/fastapi/v1/`.
- [x] Add OpenAPI assertions for the new route contract.
- [x] Add Command Center adapter assertions by keeping the registry aligned with
      public OpenAPI operations.
- [x] Run focused FastAPI v1 tests.
- [x] Run import sanity for `apps.v1.main`.
- [x] Run `git diff --check`.
