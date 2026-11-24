# Asset-Indexed Updaters

`AssetIndexedUpdater` is the markets-specific base class for updaters whose
rows are keyed by a Main Sequence market asset. It keeps asset identity out of
core MainSequence behavior while giving market datasets a consistent asset dimension,
asset scoping API, namespace behavior, and source-table relationship to
`AssetTable`.

Use this page for timestamped asset facts such as snapshots, pricing details,
prices, signals, weights, holdings, or any table whose natural row identity is
`(time_index, asset_identifier)`.

## How It Differs From A Normal TimeIndexTableUpdater

A normal Main Sequence `TimeIndexTableUpdater` is a generic data product. It owns a stable
published dataset contract, update logic, persistence, hashing, dependencies,
and orchestration behavior. It does not know that one of its dimensions is a
market asset.

`AssetIndexedUpdater` adds the market layer:

- the canonical asset storage dimension is `asset_identifier`;
- `asset_list` is an optional updater scope, not table meaning;
- `get_asset_list()` validates string, mapping, or object asset scopes;
- asset scopes can be translated into TimeIndexTableUpdater `dimension_filters`;
- per-asset update ranges are exposed through helpers such as
  `get_asset_dimension_range_map_great_or_equal(...)`;
- the default `hash_namespace` is `mainsequence.markets`;
- the registered storage class declares a foreign key from `asset_identifier` to
  `AssetTable.unique_identifier`.

```text
+-----------------------------+           generic TimeIndexTableUpdater        +-----------------------------+
| metatables.                 |---------------------------------->| TimeIndexMetaTable storage   |
| TimeIndexTableUpdater                    |                                   | registered from storage cls |
|-----------------------------|                                   |-----------------------------|
| physical_table_name         |                                   | published table             |
| update_hash                 |                                   | schema / columns            |
| dependencies()              |                                   | update history              |
| update()                    |                                   +-----------------------------+
+-----------------------------+
              ^
              |
              | adds markets asset conventions
              |
+-----------------------------+           asset-indexed          +-----------------------------+
| AssetIndexedUpdater         |---------------------------------->| AssetTable                  |
|-----------------------------|       asset_identifier FK         |-----------------------------|
| asset_identity_dimension    |                                   | unique_identifier unique    |
| asset_list update scope     |                                   | asset_type                  |
| dimension filter helpers    |                                   +-----------------------------+
| per-asset range helpers     |
+-----------------------------+
```

The important distinction is identity. A generic TimeIndexTableUpdater can publish any table
shape. An asset-indexed TimeIndexTableUpdater publishes a market table where
`asset_identifier` contains an `Asset.unique_identifier` value.

## `time_index` Is The Time Of Observation

The library is event driven. Every row of a time-indexed table is an event, and
its `time_index` is the instant its values became known. This holds for every
time-indexed table: prices, signals, weights, holdings and snapshots.

For price bars this is critical:

- A bar is stamped at its **end**. A daily bar is stamped at its session close,
  because its `close` is not known before then. The bar's start goes in
  `open_time`.
- A bar stamped at its **open** is not handled. Many vendors label a bar with
  the start of its interval. Published that way, the row says its close was
  known at the open, and every reader that takes the latest row at or before a
  timestamp uses a price from the future. Nothing detects it and there is no
  setting for it.
- A source that receives bars labelled by their start publishes them at their
  end.

## Core Contract

Asset-indexed tables should follow this shape unless a specific dataset has a
documented reason not to:

```text
+-----------------------------+      source-table FK       +-----------------------------+
| AssetIndexedUpdater table   |--------------------------->| AssetTable                  |
|-----------------------------| asset_identifier           |-----------------------------|
| time_index           index  |                            | uid                         |
| asset_identifier     index  |                            | unique_identifier unique    |
| value columns               |                            | asset_type                  |
+-----------------------------+                            +-----------------------------+
```

The `asset_identifier` column should not be an arbitrary provider ticker. It
should contain the same canonical identifier registered through
`msm.api.assets.Asset.unique_identifier`. Provider-specific tickers, FIGIs,
ISINs, symbols, and raw payloads belong either in provider detail tables, such
as `OpenFigiAssetDetailsTable`, or in TimeIndexTableUpdater value columns when the table is
explicitly a timestamped provider fact.

The `AssetIndexedUpdaterConfiguration.asset_list` field is updater scope. Asset
universe selection affects update identity, not the storage identity of the
published dataset. Two updater jobs can write different asset subsets into the
same dataset when the schema and dataset meaning are otherwise the same.

String scope items are interpreted directly as canonical asset identifiers.
Mapping scope items use `asset_identifier` as the canonical key, including when
that key is nested under `metadata`; mapping payloads must not contain
`unique_identifier`, even when `asset_identifier` is also present. Object scope
items must expose `.asset_identifier`; `.unique_identifier` is not consulted.
The same resolver is used by inherited
`AssetIndexedUpdater` validation and by the portfolio price updater, so one
mapping shape cannot pass one stage and fail the next.

```python
asset_list = [
    "asset_crypto_btc",
    {"asset_identifier": "asset_crypto_eth"},
]
```

A scope names assets and nothing else. The price updater refuses a mapping with
a `calendar` key: an asset's trading calendar is its stored link (see
"Trading Calendar" below).

## Trading Calendar

`AssetCalendar` links an asset to the stored `Calendar` whose sessions decide
which price bars the asset has. It is a one-to-one detail table of `Asset`.

```python
from msm.api.assets import Asset, AssetCalendar
from msm.api.calendars import Calendar

nyse = Calendar.create_from_pandas_calendar("NYSE")
asset = Asset.upsert(unique_identifier="asset_us_equity_acme", asset_type="equity")
AssetCalendar.upsert(asset_uid=asset.uid, calendar_uid=nyse.uid)
```

- An asset has at most one trading calendar. An asset that needs none, such as a
  currency, has no row.
- Name the calendar when the asset is registered:
  `Asset.upsert_many([{..., "calendar_identifier": "NYSE"}])`. Every payload that
  writes an asset takes `calendar_identifier` or `calendar_uid`, and so does each
  asset of an account registration.
- Link assets that already exist in one call, by identifier:
  `AssetCalendar.link_many(["asset_us_equity_acme", ...], calendar_identifier="NYSE")`.
  It writes one transaction and returns `linked`, `moved`, `unchanged`, `kept`
  and `unknown`.
- `AssetCalendar.unlinked_assets(asset_type=...)` lists the assets with no
  trading calendar, and `AssetCalendar.delete(asset_uid)` removes a link. The
  design is
  [ADR 0057](../../../ADR/0057-asset-calendar-links-in-bulk-and-at-registration.md).
- There is no default calendar. `InterpolatedPrices` resolves the calendar of
  every asset in its scope before it reads a bar. When an asset has no link, the
  whole run fails and the error names each such asset. Link the asset and run
  again.
- An asset that trades around the clock is linked to a stored 24/7 calendar, like
  any other.
- Bars and portfolio rebalance dates read the same stored calendars, so a
  correction made to a calendar by hand moves both.
- A calendar cannot be deleted while an asset is linked to it. Deleting an asset
  removes its link.

Asset-scoped configuration has two categories:

- normal `TimeIndexTableUpdateConfig` fields, which enter `update_hash`
- `ClassVar[...]` invariants, which are not Pydantic fields and do not enter
  `update_hash`

Use `Field(...)` for every config field, with a useful `description` and
`examples=[...]` when possible:

```python
from typing import ClassVar

from pydantic import Field

from metatables import TimeIndexTableUpdateConfig


class AssetIndexedUpdaterConfiguration(TimeIndexTableUpdateConfig):
    asset_list: list | None = Field(
        default=None,
        description=(
            "Optional asset unique identifier scope for this updater run. "
            "Changing it changes update identity, not table identity."
        ),
        examples=[["asset_us_equity_aapl", "asset_us_equity_msft"]],
    )
    asset_category_unique_identifier: str | None = Field(
        default=None,
        description=(
            "Optional asset category unique identifier used to resolve the "
            "updater asset universe."
        ),
        examples=["us_equities"],
    )
    reference_dimension: ClassVar[str] = "asset_identifier"
```

`asset_list` and `asset_category_unique_identifier` are fields because they
select the updater scope and must affect `update_hash`. `reference_dimension` is
a `ClassVar` because it is a fixed implementation invariant, not run
configuration.

Do not use legacy platform metadata markers to remove TimeIndexTableUpdater config fields
from hashing. There is no third asset-scope case: if it is a config field, it is
hashed; if it is not hashed, it must not be a config field.

## Set-Based Observation Reads

`AssetIndexedUpdater.get_last_observation(...)` preserves the generic
MetaTables updater dimension-query contract. Callers may pass `dimension_filters`,
`index_coordinates`, and `dimension_range_map` together while the markets layer
validates and applies the optional `asset_list` scope. Multidimensional range
coordinates must contain every identity dimension from the storage table.

Portfolio and signal workflows use this contract to retrieve the latest seed
observation for all required assets in one backend request. They do not issue
one request per asset.

## Canonical Foreign Key

In the current storage-first architecture, the schema contract lives on a
storage class
(`PlatformTimeIndexMetaTable` / `MarketsTimeIndexMetaTableMixin`), not on the
TimeIndexTableUpdater configuration. The canonical asset foreign key is a
SQLAlchemy `ForeignKey(...)` declaration on the storage class
`asset_identifier` column. The TimeIndexTableUpdater uses its storage class through
`_required_output_table()`.

Project-local storage classes should inherit from an abstract project mixin that
sets the project's default `__metatable_namespace__` and, when needed,
`__markets_storage_app__`. Concrete storage classes declare
`__markets_base_identifier__` as the bare storage concept. ms-markets combines
the namespace and base identifier into the globally unique catalog/runtime
identity. Set the mixin attributes before model import/mapping.

Project-local storage classes are declared on the project's own declarative
base, never on `MarketsBase`, which is for built-in ms-markets models. The
project's migration provider targets that base's metadata, and the foreign key
passes Markets' column object.

The project mixin namespace is final. Isolated tests and examples use a
[separate database](../../../concepts.md#namespaces-and-sandboxes) with the same names.

```python
import datetime

import pandas as pd
from metatables import sqlalchemy_naming_convention
from sqlalchemy import DateTime, Float, ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from msm.base import MarketsTimeIndexMetaTableMixin
from msm.time_index.assets import AssetUpdaterConfiguration, AssetTimestampedUpdater
from msm.models.assets.core import AssetTable


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class MyProjectMarketsStorageMixin(MarketsTimeIndexMetaTableMixin):
    __abstract__ = True
    __metatable_namespace__ = "com.my_project"
    __markets_storage_app__ = "my_project_markets"


class ExampleAssetMetricStorage(MyProjectMarketsStorageMixin, Base):
    __markets_base_identifier__ = "ExampleAssetMetricsTS"
    __metatable_description__ = (
        "Timestamped asset metric observations keyed by asset identifier "
        "for market analytics and portfolio workflows."
    )
    __time_index_name__ = "time_index"
    __index_names__ = ["time_index", "asset_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time", "description": "UTC observation timestamp."},
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(AssetTable.__table__.c.unique_identifier, ondelete="RESTRICT"),
        nullable=False,
        info={"label": "Asset", "description": "AssetTable.unique_identifier value."},
    )
    metric_value: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Metric Value", "description": "Example asset metric."},
    )


class ExampleAssetMetricConfiguration(AssetUpdaterConfiguration):
    pass


class ExampleAssetMetric(AssetTimestampedUpdater):
    configuration_class = ExampleAssetMetricConfiguration

    @classmethod
    def _required_output_table(cls) -> type[ExampleAssetMetricStorage]:
        return ExampleAssetMetricStorage

    @classmethod
    def build_frame(cls, rows: list[dict]) -> pd.DataFrame:
        return cls.validate_frame(pd.DataFrame(rows))

    def set_metrics(self, rows: list[dict]):
        return self.set_frame(self.build_frame(rows))
```

Add the storage class to the model registry of the migration provider that owns
it, so that provider registers it after the `Asset` MetaTable dependency: the
markets registry for a built-in ms-markets table, or the project's own provider
for a project table. Runtime startup can then attach it with
`msm.start_engine(models=[...])`. Do not call
`PlatformTimeIndexMetaTable.register(...)`, manually bind storage by UID, or
reconstruct a generic `MetaTable` in application code.

Use `__metatable_description__` for durable table discovery text. The description
should explain the market intention, row grain, and downstream use of the
asset-indexed dataset, not only list its columns.

## AssetSnapshot

`AssetSnapshot` is the live implementation of the asset-indexed pattern in
`msm.time_index.assets`. Its implementation lives in
`msm.time_index.assets.snapshots`, while the package re-exports the public
classes for normal user imports. It stores timestamped display facts about an asset,
such as name, ticker, exchange code, and share-class grouping. These are not
columns on `AssetTable` because they can change through time and can differ by
provider or observation date.

```text
+-----------------------------+      canonical FK        +-----------------------------+
| AssetSnapshot TimeIndexTableUpdater      |------------------------->| AssetTable                  |
|-----------------------------| asset_identifier         |-----------------------------|
| time_index           index  |                          | unique_identifier unique    |
| asset_identifier     index  |                          | asset_type                  |
| name                        |                          +-----------------------------+
| ticker                      |
| exchange_code               |
| asset_ticker_group_id       |
+-----------------------------+
```

`AssetSnapshotsStorage` (in `msm.time_index.assets.storage`) declares the persisted
schema as SQLAlchemy mapped columns and owns the canonical
`asset_identifier -> AssetTable.unique_identifier` foreign key. `AssetSnapshot`
uses it through `_required_output_table()`.

## Register Assets Before Publishing Snapshots

Asset snapshots should refer to assets that already exist in `AssetTable`.
Application code normally registers the asset type and asset through the typed
row API before running an asset-indexed TimeIndexTableUpdater.

```python
import msm

from msm.api.assets import Asset, AssetType

msm.start_engine(models=["AssetType", "Asset"])

AssetType.upsert(asset_type="crypto", display_name="Crypto")
Asset.upsert(unique_identifier="example-asset-btc", asset_type="crypto")
```

For explicit startup preflight, register the required MetaTable before source
table initialization:

```python
import msm

runtime = msm.start_engine(models=["Asset"])
```

## Building And Running AssetSnapshot

Use `AssetSnapshot.build_frame(...)` when you want local frame validation, and
`AssetSnapshot().set_snapshots(...)` when you want to attach rows to a node before
running it.

```python
from datetime import UTC, datetime

from msm.time_index.assets import AssetSnapshot

snapshots = [
    {
        "time_index": datetime.now(UTC),
        "asset_identifier": "example-asset-btc",
        "name": "Bitcoin",
        "ticker": "BTC",
        "exchange_code": "CRYPTO",
        "asset_ticker_group_id": "crypto-majors",
    }
]

snapshot_frame = AssetSnapshot.build_frame(snapshots)
snapshot_node = AssetSnapshot().set_snapshots(snapshots)
result_frame = snapshot_node.run()
```

Each snapshot row must carry its own `time_index`. `AssetSnapshot` validates the
frame, normalizes timestamps to `datetime64[ns, UTC]`, sets the
`["time_index", "asset_identifier"]` MultiIndex, and rejects duplicate keys
inside the frame.

Before a run persists rows, `AssetSnapshot` checks the backend for existing
`(time_index, asset_identifier)` keys. A row stored with the same values is
dropped, so republishing it writes nothing; a key stored with different values
fails the run with `ValueError`. Publish corrections as a new timestamped
snapshot instead of overwriting the previous observation.

`AssetSnapshots.publish(...)` (in `msm.api.assets`) goes further: it compares
each row with the snapshot in effect at its own `time_index` (the asset's latest
stored row at or before it, or the asset's previous row in the batch when that
is later) on `name`, `ticker`, `exchange_code` and `asset_ticker_group_id`, and
writes only the rows that change it. It returns an `AssetSnapshotPublication`
with the `written` and `skipped` counts, and starts no update run when every
row is unchanged.

## Shared Stamped Base

Timestamped reference-data facts share the same frame mechanics whether the
reference row is an asset or an index. Non-model-specific TimeIndexTableUpdater helpers live
under `msm.time_index.utils`; the generic stamped base lives in
`msm.time_index.utils.stamped`:

- `StampedFrameMixin` owns real frame binding, validation, and
  `datetime64[ns, UTC]` normalization — all sourced from the registered
  `output_table` (`__table__.columns`, `__index_names__`,
  `__time_index_name__`). It does not create placeholder rows for schema
  registration.
- `StampedUpdater` owns the empty dependency default and the markets
  `hash_namespace` defaulting rule, and resolves its storage class through
  `_required_output_table()`.

Asset-specific classes live under `msm.time_index.assets` and use storage
classes that add the `AssetTable.unique_identifier` foreign key. Index-specific
classes live under `msm.time_index.indices` and reuse the same stamped base with
storage classes carrying the `IndexTable.unique_identifier` foreign key. Shared
utility modules such as `msm.time_index.utils.stamped` and
`msm.time_index.utils.namespaces` stay concept-neutral and do not sit beside
model-specific packages at the `msm.time_index` root.

## Namespaces And Identifiers

Markets updaters use the same namespace rule as markets MetaTables because
their default identifiers derive from their storage classes. In the Markets
namespace, logical identifiers stay bare, such as `Asset` and
`AssetSnapshotsTS`; `AssetSnapshot._default_identifier()` derives the latter from
`AssetSnapshotsStorage.metatable_identifier()`. A storage class in a project's
namespace carries that namespace as its prefix, such as `my-provider.BarsTS`.

The default TimeIndexTableUpdater `hash_namespace` is `mainsequence.markets`.
Pass an explicit `hash_namespace` only for isolated experiments, tests, or
parallel runs that must not collide on a shared backend.

## Related Code

- `src/msm/time_index/assets/asset_indexed.py`: base class, asset scope validation,
  namespace behavior, `asset_identifier` filters, and per-asset update range helpers.
- `src/msm/time_index/assets/storage.py`: asset storage classes (including
  `AssetSnapshotsStorage`) that own the schema, dtypes, and canonical `AssetTable`
  foreign keys.
- `src/msm/time_index/utils/stamped.py`: shared timestamped frame behavior
  validated against the registered `output_table`.
- `src/msm/time_index/utils/storage_schema.py`: derives column dtype maps from a
  storage class with MetaTables' dtype tokens (`sqlalchemy_type_to_token`).
- `src/msm/time_index/utils/namespaces.py`: shared markets hash-namespace
  defaulting for updaters.
- `src/msm/time_index/assets/snapshots.py`: `AssetSnapshot`,
  `AssetUpdaterConfiguration`, and timestamped asset frame validation.
- `src/msm/time_index/indices/timestamped.py`: `IndexTimestampedUpdater` and
  `IndexUpdaterConfiguration` for timestamped facts keyed to `IndexTable`.
- `src/msm_pricing/time_index/pricing_details/__init__.py`:
  `AssetPricingDetail` and its pricing-specific configuration.
- `examples/msm/assets/asset_crud_workflow.py`: asset workflow that includes
  `AssetSnapshot` frame construction and TimeIndexTableUpdater execution.
- `docs/knowledge/msm/migrations/index.md`: current storage registration and
  migration workflow for MetaTables and time-index storage tables.
