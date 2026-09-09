"""Reusable builders and query validation for resource discovery endpoints."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from .bulk_actions import BulkActionDefinition
from .collections import (
    ResourceBooleanFilter,
    ResourceColumn,
    ResourceDescriptor,
    ResourceDiscovery,
    ResourceFilter,
    ResourceFilterOption,
    ResourceIdentity,
    ResourceListControls,
    ResourceListDiscovery,
    ResourceSearchControl,
    ResourceSelectFilter,
    ResourceTextFilter,
)

PRESENTATION_QUERY_KEYS = frozenset(
    {"light", "limit", "offset", "ordering", "page", "page_size", "sort"}
)


@dataclass(frozen=True)
class ResourceDiscoverySpec:
    """Validated discovery response plus its accepted semantic query keys."""

    response: ResourceDiscovery
    semantic_query_keys: frozenset[str]


def resolve_resource_discovery(
    spec_key: str,
    query_keys: Iterable[str],
    *,
    specs: Mapping[str, ResourceDiscoverySpec],
) -> ResourceDiscovery:
    """Resolve one discovery response after rejecting presentation and unknown keys."""

    try:
        spec = specs[spec_key]
    except KeyError as exc:
        raise LookupError(f"Resource discovery specification {spec_key!r} was not found.") from exc

    supplied = set(query_keys)
    presentation_keys = sorted(supplied.intersection(PRESENTATION_QUERY_KEYS))
    if presentation_keys:
        raise ValueError(
            "Resource discovery does not accept presentation query keys: "
            + ", ".join(presentation_keys)
            + "."
        )
    unknown = sorted(supplied.difference(spec.semantic_query_keys))
    if unknown:
        raise ValueError("Unsupported resource discovery query keys: " + ", ".join(unknown) + ".")
    return spec.response


def resource_column(
    value_path: str,
    header: str,
    data_type: Literal[
        "text", "number", "boolean", "date", "datetime", "badge", "list", "json"
    ] = "text",
    *,
    importance: Literal["primary", "secondary", "tertiary"] | None = None,
    filter_key: str | None = None,
) -> ResourceColumn:
    """Build the conventional visible column for a safe dotted value path."""

    return ResourceColumn(
        id=value_path.replace("_", "-").replace(".", "-"),
        header=header,
        value_path=value_path,
        data_type=data_type,
        default_visible=True,
        hideable=True,
        importance=importance,
        filter_key=filter_key,
    )


def resource_text_filter(key: str, label: str) -> ResourceTextFilter:
    return ResourceTextFilter(key=key, label=label)


def resource_boolean_filter(key: str, label: str) -> ResourceBooleanFilter:
    return ResourceBooleanFilter(key=key, label=label)


def resource_select_filter(
    key: str,
    label: str,
    values: tuple[tuple[str, str], ...],
) -> ResourceSelectFilter:
    return ResourceSelectFilter(
        key=key,
        label=label,
        options=[
            ResourceFilterOption(value=value, label=option_label) for value, option_label in values
        ],
    )


def build_resource_discovery_spec(
    *,
    resource_id: str,
    label: str,
    item_label: str,
    identity_fields: tuple[str, ...],
    columns: tuple[ResourceColumn, ...],
    search: bool = False,
    filters: tuple[ResourceFilter, ...] = (),
    bulk_actions: tuple[BulkActionDefinition, ...] = (),
) -> ResourceDiscoverySpec:
    """Build validated discovery metadata for one provider resource list."""

    semantic_query_keys = {item.key for item in filters}
    search_control = None
    if search:
        semantic_query_keys.add("search")
        search_control = ResourceSearchControl(
            placeholder=f"Search {item_label}",
            fields=[column.id for column in columns],
        )
    return ResourceDiscoverySpec(
        response=ResourceDiscovery(
            resource=ResourceDescriptor(
                id=resource_id,
                label=label,
                item_label=item_label,
                identity=ResourceIdentity(fields=list(identity_fields)),
            ),
            list=ResourceListDiscovery(
                controls=ResourceListControls(
                    search=search_control,
                    filters=list(filters),
                    ordering=[],
                ),
                columns=list(columns),
            ),
            bulk_actions=list(bulk_actions),
        ),
        semantic_query_keys=frozenset(semantic_query_keys),
    )


__all__ = [
    "PRESENTATION_QUERY_KEYS",
    "ResourceDiscoverySpec",
    "build_resource_discovery_spec",
    "resolve_resource_discovery",
    "resource_boolean_filter",
    "resource_column",
    "resource_select_filter",
    "resource_text_filter",
]
