from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from msm.time_index.assets.asset_indexed import asset_scope_identifier
from msm.settings import ASSET_IDENTIFIER_DIMENSION

ASSET_IDENTIFIER = ASSET_IDENTIFIER_DIMENSION

_MISSING = object()


def asset_field(asset: Any, field_name: str, default: Any = _MISSING) -> Any:
    """Read an asset field from an object, mapping, or metadata payload."""

    value = _MISSING
    if isinstance(asset, Mapping):
        value = asset.get(field_name, _MISSING)
        metadata = asset.get("metadata") or {}
    else:
        value = getattr(asset, field_name, _MISSING)
        metadata = getattr(asset, "metadata", None) or {}

    if value is _MISSING and isinstance(metadata, Mapping):
        value = metadata.get(field_name, _MISSING)

    if value is _MISSING:
        if default is _MISSING:
            raise AttributeError(f"Asset scope item does not expose {field_name!r}.")
        return default

    return value


def asset_unique_identifier(asset: Any) -> str:
    value = asset_scope_identifier(asset, identity_dimension=ASSET_IDENTIFIER)
    if not value.strip():
        raise TypeError("Asset scope item requires a non-empty asset_identifier string.")
    return value


def refuse_scope_calendar(asset: Any) -> None:
    """Refuse a scope mapping that still names a calendar (ADR 0056).

    An asset's trading calendar is its ``AssetCalendar`` link. A ``calendar`` key
    in a scope mapping is no longer read, so it is refused instead of ignored.
    """

    if not isinstance(asset, Mapping):
        return
    metadata = asset.get("metadata")
    if "calendar" in asset or (isinstance(metadata, Mapping) and "calendar" in metadata):
        raise TypeError(
            "Asset scope mappings must not contain 'calendar'. An asset's trading "
            "calendar is its AssetCalendar link: "
            "AssetCalendar.upsert(asset_uid=..., calendar_uid=...)."
        )


def asset_display_name(asset: Any) -> str:
    return asset_field(asset, "name", asset_unique_identifier(asset))


def dedupe_asset_scope(asset_list: Iterable[Any]) -> list[Any]:
    assets = list(asset_list)
    deduped: dict[str, Any] = {}
    for asset in assets:
        deduped[asset_unique_identifier(asset)] = asset
    return list(deduped.values())


def require_asset_scope(asset_list: Iterable[Any] | None, *, context: str) -> list[Any]:
    if asset_list is None:
        raise ValueError(f"{context} requires an explicit asset_list.")
    assets = list(asset_list)
    if not assets:
        raise ValueError(f"{context} requires a non-empty asset_list.")
    return dedupe_asset_scope(assets)


def require_asset_category_scope(
    *,
    asset_list: Iterable[Any] | None,
    asset_category_unique_id: str | None,
    context: str,
) -> list[Any]:
    if asset_list is not None:
        return require_asset_scope(asset_list, context=context)
    if asset_category_unique_id:
        raise ValueError(
            f"{context} cannot resolve asset category {asset_category_unique_id!r} "
            "inside msm. Resolve the category through MetaTable services and pass "
            "the resulting asset_list explicitly."
        )
    raise ValueError(
        f"{context} requires asset_list or a source TimeIndexTableUpdater with get_asset_list()."
    )


def asset_spot_reference_unique_identifier(asset: Any) -> str:
    get_reference = getattr(asset, "get_spot_reference_asset_unique_identifier", None)
    if callable(get_reference):
        value = get_reference()
    else:
        value = asset_field(
            asset,
            "spot_reference_asset_unique_identifier",
            asset_field(asset, "spot_reference_unique_identifier", asset_unique_identifier(asset)),
        )
    if not isinstance(value, str) or not value.strip():
        raise TypeError(
            "Asset scope item requires a spot reference unique identifier for this operation."
        )
    return value


__all__ = [
    "ASSET_IDENTIFIER",
    "asset_display_name",
    "asset_field",
    "asset_spot_reference_unique_identifier",
    "asset_unique_identifier",
    "dedupe_asset_scope",
    "refuse_scope_calendar",
    "require_asset_category_scope",
    "require_asset_scope",
]
