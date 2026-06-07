from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from uuid import UUID

import pandas as pd
from mainsequence.logconf import logger as _mainsequence_logger

from msm.data_nodes.accounts.storage import AccountHoldingsStorage
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import search_model
from msm.services.holdings import validate_holdings_frame
from msm.settings import ASSET_IDENTIFIER_DIMENSION

from msm.data_nodes.accounts.virtual_funds.storage import VirtualFundHoldingsStorage

logger = _mainsequence_logger.bind(sub_application="markets", component="virtual_funds")


def build_virtual_fund_holdings_frame(
    *,
    allocation_time: dt.datetime | str,
    virtual_fund_uid: UUID | str,
    source_account_holdings_set_uid: UUID | str,
    virtual_fund_holdings_set_uid: UUID | str,
    allocations: Sequence[Mapping[str, Any] | Any],
    target_trade_time: dt.datetime | str | None = None,
) -> pd.DataFrame:
    if not allocations:
        raise ValueError("At least one virtual-fund allocation is required.")

    rows: list[dict[str, Any]] = []
    seen_identifiers: set[str] = set()
    duplicate_identifiers: set[str] = set()
    for raw_allocation in allocations:
        allocation = _allocation_payload(raw_allocation)
        asset_identifier = _required_allocation_string(allocation, ASSET_IDENTIFIER_DIMENSION)
        if asset_identifier in seen_identifiers:
            duplicate_identifiers.add(asset_identifier)
        seen_identifiers.add(asset_identifier)

        rows.append(
            {
                VirtualFundHoldingsStorage.__time_index_name__: allocation_time,
                "virtual_fund_uid": virtual_fund_uid,
                ASSET_IDENTIFIER_DIMENSION: asset_identifier,
                "virtual_fund_holdings_set_uid": virtual_fund_holdings_set_uid,
                "source_account_holdings_set_uid": source_account_holdings_set_uid,
                "allocated_quantity": allocation.get("allocated_quantity"),
                "direction": allocation.get("direction", 1),
                "target_trade_time": allocation.get("target_trade_time", target_trade_time),
                "extra_details": allocation.get("extra_details") or {},
            }
        )

    if duplicate_identifiers:
        raise ValueError(
            "Each virtual-fund allocation must use a unique asset_identifier. "
            "Duplicate values: " + ", ".join(sorted(duplicate_identifiers)) + "."
        )

    return validate_holdings_frame(
        pd.DataFrame(rows),
        storage_table=VirtualFundHoldingsStorage,
    )


def validate_virtual_fund_allocation_bounds(
    context: MarketsRepositoryContext,
    allocations_frame: pd.DataFrame,
) -> None:
    frame = validate_holdings_frame(
        allocations_frame,
        storage_table=VirtualFundHoldingsStorage,
    )
    flat = frame.reset_index()

    requested_by_key: dict[tuple[str, str, int], float] = defaultdict(float)
    virtual_fund_by_key: dict[tuple[str, str, int], str] = {}
    holdings_set_by_source: dict[str, set[str]] = defaultdict(set)
    for row in flat.to_dict("records"):
        source_uid = str(row["source_account_holdings_set_uid"])
        key = (
            source_uid,
            str(row[ASSET_IDENTIFIER_DIMENSION]),
            int(row["direction"]),
        )
        requested_by_key[key] += float(row["allocated_quantity"])
        virtual_fund_by_key[key] = str(row["virtual_fund_uid"])
        holdings_set_by_source[source_uid].add(str(row["virtual_fund_holdings_set_uid"]))

    source_rows = _source_account_holdings_rows(context, requested_by_key.keys())
    existing_rows = _existing_virtual_fund_allocation_rows(
        context,
        source_uids=holdings_set_by_source.keys(),
    )
    excluded_set_uids = {
        set_uid
        for source_set_uids in holdings_set_by_source.values()
        for set_uid in source_set_uids
    }
    existing_by_key: dict[tuple[str, str, int], float] = defaultdict(float)
    for row in existing_rows:
        if str(row.get("virtual_fund_holdings_set_uid")) in excluded_set_uids:
            continue
        key = (
            str(row.get("source_account_holdings_set_uid")),
            str(row.get(ASSET_IDENTIFIER_DIMENSION)),
            int(row.get("direction", 1)),
        )
        existing_by_key[key] += float(row.get("allocated_quantity") or 0)

    for key, requested_quantity in requested_by_key.items():
        source_quantity = source_rows.get(key)
        if source_quantity is None:
            _log_rejected_allocation(
                key=key,
                virtual_fund_uid=virtual_fund_by_key[key],
                source_quantity=0.0,
                existing_quantity=existing_by_key[key],
                requested_quantity=requested_quantity,
            )
            raise ValueError(
                "Virtual-fund allocation has no matching source account holding "
                f"for source_set={key[0]}, asset_identifier={key[1]}, direction={key[2]}."
            )

        existing_quantity = existing_by_key[key]
        if existing_quantity + requested_quantity > source_quantity:
            _log_rejected_allocation(
                key=key,
                virtual_fund_uid=virtual_fund_by_key[key],
                source_quantity=source_quantity,
                existing_quantity=existing_quantity,
                requested_quantity=requested_quantity,
            )
            raise ValueError(
                "Virtual-fund allocation exceeds source account holdings for "
                f"source_set={key[0]}, asset_identifier={key[1]}, direction={key[2]}."
            )


def _source_account_holdings_rows(
    context: MarketsRepositoryContext,
    keys: Iterable[tuple[str, str, int]],
) -> dict[tuple[str, str, int], float]:
    from msm.api.base import operation_result_rows

    source_uids = sorted({key[0] for key in keys})
    if not source_uids:
        return {}

    rows = operation_result_rows(
        search_model(
            context,
            model=AccountHoldingsStorage,
            filters={},
            in_filters={"holdings_set_uid": source_uids},
            limit=max(500, len(source_uids) * 100),
        )
    )
    source_rows: dict[tuple[str, str, int], float] = {}
    for row in rows:
        key = (
            str(row.get("holdings_set_uid")),
            str(row.get(ASSET_IDENTIFIER_DIMENSION)),
            int(row.get("direction", 1)),
        )
        source_rows[key] = float(row.get("quantity") or 0)
    return source_rows


def _existing_virtual_fund_allocation_rows(
    context: MarketsRepositoryContext,
    *,
    source_uids: Iterable[str],
) -> list[dict[str, Any]]:
    from msm.api.base import operation_result_rows

    source_uid_list = sorted({str(uid) for uid in source_uids})
    if not source_uid_list:
        return []
    return operation_result_rows(
        search_model(
            context,
            model=VirtualFundHoldingsStorage,
            filters={},
            in_filters={"source_account_holdings_set_uid": source_uid_list},
            limit=max(500, len(source_uid_list) * 100),
        )
    )


def _log_rejected_allocation(
    *,
    key: tuple[str, str, int],
    virtual_fund_uid: str,
    source_quantity: float,
    existing_quantity: float,
    requested_quantity: float,
) -> None:
    logger.warning(
        "Rejected virtual-fund allocation",
        source_account_holdings_set_uid=key[0],
        virtual_fund_uid=virtual_fund_uid,
        asset_identifier=key[1],
        direction=key[2],
        source_quantity=source_quantity,
        existing_allocated_quantity=existing_quantity,
        requested_quantity=requested_quantity,
    )


def _allocation_payload(allocation: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(allocation, Mapping):
        return dict(allocation)
    model_dump = getattr(allocation, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    return {
        key: getattr(allocation, key)
        for key in (
            ASSET_IDENTIFIER_DIMENSION,
            "allocated_quantity",
            "direction",
            "target_trade_time",
            "extra_details",
        )
        if hasattr(allocation, key)
    }


def _required_allocation_string(allocation: Mapping[str, Any], field_name: str) -> str:
    value = allocation.get(field_name)
    if value is None or str(value).strip() == "":
        raise ValueError(f"Virtual-fund allocations require a non-empty {field_name}.")
    return str(value)


__all__ = [
    "build_virtual_fund_holdings_frame",
    "validate_holdings_frame",
    "validate_virtual_fund_allocation_bounds",
]
