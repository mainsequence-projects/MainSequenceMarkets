"""Bring an application's execution rows to 6.0.0 (ADR 0064).

Revision ``0037`` gives each order in Markets' own ``OrdersTS`` an ``Order`` row. An
application's instances of ``OrdersTS``, ``OrderEventsTS`` and ``TradesTS`` reference
Markets' ``Order`` too, so their orders need ``Order`` rows before the application's own
revision adds that key. These helpers map an application's orders exactly as ``0037``
maps Markets' own:

- :func:`order_uid_for_identifier` is the uid an ``order_identifier`` becomes;
- :func:`orders_from_legacy_states` builds the ``Order`` rows from the instance's
  ``OrdersTS`` rows as they were before 6.0.0, for ``Order.upsert_many``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

ORDER_UID_NAMESPACE = uuid.UUID("0b8f1c52-4a77-5c7e-9d2e-6a3f0c1e8b64")
"""Namespace of the uids given to order identifiers that are not UUIDs (revision 0037)."""

ORDER_TERMS = (
    "order_side",
    "order_type",
    "quantity",
    "limit_price",
    "time_in_force",
    "expires_time",
    "client_order_id",
)
"""The terms an ``Order`` row takes from an order's earliest state row."""


def order_uid_for_identifier(identifier: str) -> uuid.UUID:
    """The uid an order identifier becomes: itself when it is a UUID, else its uuid5."""

    try:
        return uuid.UUID(str(identifier))
    except ValueError:
        return uuid.uuid5(ORDER_UID_NAMESPACE, str(identifier))


def orders_from_legacy_states(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The ``Order`` rows of pre-6.0.0 ``OrdersTS`` rows, one per order identifier.

    Each row has ``order_time``, ``order_identifier``, ``account_identifier``,
    ``asset_identifier`` and optionally ``order_manager_identifier`` and the terms. An
    order takes its account, asset, manager and terms from its earliest row; an empty
    string becomes ``None``. Raises ``ValueError`` naming the identifiers whose rows name
    more than one account or asset, which cannot be one order.
    """

    orders: dict[uuid.UUID, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for row in sorted(rows, key=lambda row: (row["order_time"], str(row["order_identifier"]))):
        identifier = str(row["order_identifier"])
        uid = order_uid_for_identifier(identifier)
        order = orders.get(uid)
        if order is None:
            orders[uid] = {
                "uid": uid,
                "account_identifier": row["account_identifier"],
                "asset_identifier": row["asset_identifier"],
                "order_manager_identifier": _blank_to_none(row.get("order_manager_identifier")),
                **{term: _blank_to_none(row.get(term)) for term in ORDER_TERMS},
            }
        elif (order["account_identifier"], order["asset_identifier"]) != (
            row["account_identifier"],
            row["asset_identifier"],
        ):
            conflicts.add(identifier)
    if conflicts:
        raise ValueError(
            "These order identifiers have rows of more than one account or asset, so they "
            f"cannot be one order: {', '.join(sorted(conflicts)[:20])}."
        )
    return list(orders.values())


def _blank_to_none(value: Any) -> Any:
    return None if value == "" else value


__all__ = [
    "ORDER_TERMS",
    "ORDER_UID_NAMESPACE",
    "order_uid_for_identifier",
    "orders_from_legacy_states",
]
