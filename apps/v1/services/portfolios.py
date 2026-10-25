from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from apps.v1.identity import registry_write
from apps.v1.schemas.common import FrontEndDetailSummary
from apps.v1.schemas.portfolios import (
    Portfolio,
    PortfolioBulkCascadeDeleteResponse,
    PortfolioBulkDeleteResponse,
    PortfolioCascadeDeleteResponse,
    PortfolioDatasetReconciliationResult,
    PortfolioDatasetReconcileRequest,
    PortfolioDatasetRegistrationRequest,
    PortfolioDatasetState,
    PortfolioDeleteResponse,
    PortfolioDetailResponse,
    PortfolioWeightsDeleteResponse,
    PortfolioWeightsSnapshotResponse,
    PortfolioWithIncludes,
)
from msm.api.http import (
    BulkDeletePreflightResponse,
    TabularFrameResponse,
    build_tabular_field,
    build_tabular_frame,
)

PORTFOLIOS_VALUES_OPERATION_ID = "getPortfoliosValuesFrame"
PORTFOLIOS_WEIGHTS_OPERATION_ID = "getPortfoliosWeightsFrame"


class PortfolioDataIntegrityError(ValueError):
    """Raised when stored portfolio rows violate the current portfolio contract."""


def list_portfolios(
    *,
    search: str = "",
    calendar_uid: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    runtime = _get_runtime()
    response = _list_portfolio_rows_response(
        runtime.context,
        search=search,
        calendar_uid=calendar_uid,
        limit=limit,
        offset=offset,
    )
    return {
        "count": int(response["count"]),
        "results": [_validate_portfolio_row(row) for row in response["results"]],
    }


def get_portfolio_detail(*, uid: str) -> PortfolioDetailResponse | None:
    runtime = _get_runtime()
    response = _get_portfolio_detail_response(runtime.context, uid=uid)
    if response is None:
        return None
    if isinstance(response, Mapping) and "portfolio" in response:
        _validate_portfolio_row(response["portfolio"])
    return PortfolioDetailResponse.model_validate(response)


def get_portfolio_summary(*, uid: str) -> FrontEndDetailSummary | None:
    runtime = _get_runtime()
    response = _get_portfolio_frontend_detail_summary(runtime.context, uid=uid)
    if response is None:
        return None
    return FrontEndDetailSummary.model_validate(response)


def get_portfolio_weights(
    *,
    uid: str,
    order: str = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    weights_date: dt.datetime | None = None,
) -> PortfolioWeightsSnapshotResponse | None:
    runtime = _get_runtime()
    response = _get_portfolio_weights_snapshot_response(
        runtime.context,
        uid=uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        weights_date=weights_date,
    )
    if response is None:
        return None
    return PortfolioWeightsSnapshotResponse.model_validate(response)


def get_portfolio_signal_weights_frame(
    *,
    uid: str,
    start_date: dt.datetime | None = None,
    end_date: dt.datetime | None = None,
    order: str = "desc",
    limit: int = 50,
) -> TabularFrameResponse | None:
    runtime = _get_runtime()
    response = _get_portfolio_signal_weights_frame_response(
        runtime.context,
        uid=uid,
        start_date=start_date,
        end_date=end_date,
        order=order,
        limit=limit,
    )
    if response is None:
        return None
    return TabularFrameResponse.model_validate(response)


def get_portfolio_values_frame(
    *,
    uid: str,
    start_date: dt.datetime | None = None,
    end_date: dt.datetime | None = None,
    order: str = "desc",
    limit: int = 50,
) -> TabularFrameResponse | None:
    runtime = _get_runtime()
    response = _get_portfolio_values_frame_response(
        runtime.context,
        uid=uid,
        start_date=start_date,
        end_date=end_date,
        order=order,
        limit=limit,
    )
    if response is None:
        return None
    return TabularFrameResponse.model_validate(response)


def get_portfolios_by_uids(
    *, uids: Sequence[str], include: Sequence[str] | None = None
) -> list[PortfolioWithIncludes]:
    """Return the portfolios whose uid is listed, in request order; unknown uids are omitted.

    ``include`` names provider sidecar MetaTables keyed by `Portfolio.uid` whose
    rows are attached under ``includes`` (ADR 0047 `include` hydration).
    """

    from apps.v1.services.includes import hydrate
    from apps.v1.services.lookups import normalize_lookup_uids, rows_by_uids
    from msm.models import PortfolioTable

    runtime = _get_runtime()
    rows = rows_by_uids(runtime.context, model=PortfolioTable, uids=normalize_lookup_uids(uids))
    return hydrate(
        runtime.context,
        model_cls=PortfolioWithIncludes,
        core_model=PortfolioTable,
        items=[_validate_portfolio_row(row) for row in rows],
        include=include,
    )


def get_portfolios_values_frame(
    *,
    uids: Sequence[str],
    start_date: dt.datetime | None = None,
    end_date: dt.datetime | None = None,
    order: str = "desc",
    limit: int = 500,
) -> TabularFrameResponse:
    """Return one `core.tabular_frame@v1` of values for several portfolios.

    ADR 0047: the portfolios are grouped by the `PortfoliosTS` instance the
    catalog records for them; each instance is read once and the rows are
    merged. Every requested uid must be a portfolio.
    """

    portfolios = _required_portfolios(uids)
    rows = _portfolio_values(
        [portfolio.unique_identifier for portfolio in portfolios],
        start=start_date,
        end=end_date,
        repository_context=_get_runtime().context,
    )
    rows.sort(
        key=lambda row: (_sort_time(row.get("time_index")), str(row.get("portfolio_identifier"))),
        reverse=order == "desc",
    )
    rows = rows[:limit]
    columns = [
        "time_index",
        "portfolio_identifier",
        "portfolio_uid",
        "close",
        "return",
        "calculated_close",
        "close_time",
    ]
    field_types = {
        "time_index": "datetime",
        "portfolio_identifier": "string",
        "portfolio_uid": "string",
        "close": "number",
        "return": "number",
        "calculated_close": "number",
        "close_time": "datetime",
    }
    return build_tabular_frame(
        columns=columns,
        rows=[
            {
                "time_index": _json_datetime(row.get("time_index")),
                "portfolio_identifier": row.get("portfolio_identifier"),
                "portfolio_uid": _json_uid(row.get("portfolio_uid")),
                "close": row.get("close"),
                "return": row.get("return", row.get("return_")),
                "calculated_close": row.get("calculated_close"),
                "close_time": _json_datetime(row.get("close_time")),
            }
            for row in rows
        ],
        fields=[
            build_tabular_field(
                key=column,
                label=column.replace("_", " ").title(),
                field_type=field_types[column],
                nullable=column not in {"time_index", "portfolio_identifier"},
            )
            for column in columns
        ],
        meta={
            "timeSeries": {
                "shape": "long",
                "timeField": "time_index",
                "valueField": "close",
                "seriesField": "portfolio_identifier",
                "sorted": True,
            }
        },
        source={
            "kind": "api",
            "id": PORTFOLIOS_VALUES_OPERATION_ID,
            "label": "Portfolio values",
            "context": {
                "portfolio_uids": [str(portfolio.uid) for portfolio in portfolios],
                "start_date": _json_datetime(start_date),
                "end_date": _json_datetime(end_date),
                "order": order,
                "limit": limit,
            },
        },
    )


def get_portfolios_weights_frame(
    *,
    uids: Sequence[str],
    weights_date: dt.datetime | None = None,
    as_of: bool = True,
) -> TabularFrameResponse:
    """Return one `core.tabular_frame@v1` of weight snapshots for several portfolios."""

    portfolios = _required_portfolios(uids)
    rows = _latest_portfolio_weights(
        [portfolio.unique_identifier for portfolio in portfolios],
        weights_date=weights_date,
        as_of=as_of,
        repository_context=_get_runtime().context,
    )
    columns = [
        "time_index",
        "portfolio_identifier",
        "portfolio_uid",
        "asset_identifier",
        "weight",
        "weight_before",
        "price_current",
        "price_before",
        "volume_current",
        "volume_before",
    ]
    field_types = {column: "number" for column in columns}
    field_types.update(
        time_index="datetime",
        portfolio_identifier="string",
        portfolio_uid="string",
        asset_identifier="string",
    )
    return build_tabular_frame(
        columns=columns,
        rows=[
            {
                **{column: row.get(column) for column in columns},
                "time_index": _json_datetime(row.get("time_index")),
                "portfolio_uid": _json_uid(row.get("portfolio_uid")),
            }
            for row in rows
        ],
        fields=[
            build_tabular_field(
                key=column,
                label=column.replace("_", " ").title(),
                field_type=field_types[column],
                nullable=column not in {"time_index", "portfolio_identifier", "asset_identifier"},
            )
            for column in columns
        ],
        meta={
            "timeSeries": {
                "shape": "long",
                "timeField": "time_index",
                "valueField": "weight",
                "seriesField": "asset_identifier",
                "sorted": True,
            }
        },
        source={
            "kind": "api",
            "id": PORTFOLIOS_WEIGHTS_OPERATION_ID,
            "label": "Portfolio weights",
            "context": {
                "portfolio_uids": [str(portfolio.uid) for portfolio in portfolios],
                "weights_date": _json_datetime(weights_date),
                "as_of": as_of,
            },
        },
    )


@registry_write("portfolio", "register:datasets")
def register_portfolio_dataset_catalog(
    *,
    uid: str,
    payload: PortfolioDatasetRegistrationRequest,
) -> PortfolioDatasetState:
    """Record which instance tables hold one portfolio's datasets (ADR 0047)."""

    from msm_portfolios.services import register_portfolio_datasets

    return register_portfolio_datasets(
        _get_runtime().context,
        {
            "portfolio_uid": uuid.UUID(str(uid)),
            "values_meta_table_uid": payload.values_meta_table_uid,
            "weights_meta_table_uid": payload.weights_meta_table_uid,
            "signal_meta_table_uid": payload.signal_meta_table_uid,
        },
        reconcile=payload.reconcile,
    )


def get_portfolio_dataset_state(*, uid: str) -> PortfolioDatasetState | None:
    """Return the catalog row of one portfolio, or ``None`` when it reads the core tables.

    Raises ``LookupError`` when the portfolio does not exist.
    """

    from msm_portfolios.services import list_portfolio_dataset_states

    if get_portfolio_detail(uid=uid) is None:
        raise LookupError(f"Portfolio {uid!r} was not found.")
    states = list_portfolio_dataset_states(_get_runtime().context, portfolio_uids=[uid])
    return states[0] if states else None


@registry_write("portfolio", "reconcile:datasets")
def reconcile_portfolio_dataset_catalog(
    *,
    payload: PortfolioDatasetReconcileRequest,
) -> PortfolioDatasetReconciliationResult:
    """Reconcile the values instance of the selected catalogued portfolios."""

    from msm_portfolios.services import reconcile_portfolio_dataset_availability

    return reconcile_portfolio_dataset_availability(
        _get_runtime().context,
        portfolio_uids=payload.portfolio_uids,
        portfolio_identifiers=payload.portfolio_identifiers,
    )


def _required_portfolios(uids: Sequence[str]) -> list[Portfolio]:
    from apps.v1.services.lookups import normalize_lookup_uids

    requested = normalize_lookup_uids(uids)
    portfolios = get_portfolios_by_uids(uids=[str(item) for item in requested])
    found = {portfolio.uid for portfolio in portfolios}
    missing = [str(item) for item in requested if item not in found]
    if missing:
        raise LookupError(f"Portfolios were not found: {missing}")
    return portfolios


def _portfolio_values(identifiers: Sequence[str], **kwargs: Any) -> list[dict[str, Any]]:
    from msm_portfolios.services import portfolio_values

    return portfolio_values(list(identifiers), **kwargs)


def _latest_portfolio_weights(identifiers: Sequence[str], **kwargs: Any) -> list[dict[str, Any]]:
    from msm_portfolios.services import latest_portfolio_weights

    return latest_portfolio_weights(list(identifiers), **kwargs)


def _sort_time(value: Any) -> float:
    if value is None:
        return float("-inf")
    moment = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.timestamp()


def _json_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return str(value)


def _json_uid(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


@registry_write("portfolio", "delete")
def delete_portfolio(*, uid: str) -> PortfolioDeleteResponse | None:
    runtime = _get_runtime()
    deleted = _delete_portfolio_record(runtime.context, uid=uid)
    if not deleted:
        return None
    return PortfolioDeleteResponse.model_validate(deleted)


@registry_write("portfolio", "cascade-delete")
def cascade_delete_portfolio(*, uid: str) -> PortfolioCascadeDeleteResponse | None:
    runtime = _get_runtime()
    deleted = _cascade_delete_portfolio_record(runtime.context, uid=uid)
    if not deleted:
        return None
    return PortfolioCascadeDeleteResponse.model_validate(deleted)


@registry_write("portfolio", "delete:portfolio-weights")
def delete_portfolio_weights(
    *,
    uid: str,
    weights_date: dt.datetime | None = None,
) -> PortfolioWeightsDeleteResponse | None:
    runtime = _get_runtime()
    response = _delete_portfolio_weights(runtime.context, uid=uid, weights_date=weights_date)
    if response is None:
        return None
    return PortfolioWeightsDeleteResponse.model_validate(response)


@registry_write("portfolio", "bulk-delete")
def bulk_delete_portfolios(*, uids: list[str]) -> PortfolioBulkDeleteResponse:
    runtime = _get_runtime()
    response = _bulk_delete_portfolio_records(runtime.context, uids=uids)
    return PortfolioBulkDeleteResponse.model_validate(response)


def preflight_bulk_delete_portfolios(*, uids: list[str]) -> BulkDeletePreflightResponse:
    runtime = _get_runtime()
    target_uids = list(dict.fromkeys(uids))
    matched_count = 0
    blockers: list[str] = []
    warnings: list[str] = []
    for uid in target_uids:
        exists, resource_blockers, resource_warnings = _portfolio_delete_preflight_item(
            runtime.context,
            uid=uid,
        )
        if not exists:
            blockers.append(f"Portfolio {uid} was not found.")
            continue
        matched_count += 1
        blockers.extend(f"Portfolio {uid}: {blocker}" for blocker in resource_blockers)
        warnings.extend(f"Portfolio {uid}: {warning}" for warning in resource_warnings)
    impact = _portfolio_delete_impact()
    blockers.extend(impact.blockers)

    allowed = bool(target_uids) and not blockers
    detail = (
        f"{matched_count} portfolio{' is' if matched_count == 1 else 's are'} ready for deletion."
        if allowed
        else "The portfolio selection cannot be deleted as submitted."
    )
    return BulkDeletePreflightResponse(
        allowed=allowed,
        detail=detail,
        matched_count=matched_count,
        blockers=blockers,
        warnings=[*warnings, *impact.warnings],
        impact=impact.impact,
    )


@registry_write("portfolio", "bulk-cascade-delete")
def bulk_cascade_delete_portfolios(*, uids: list[str]) -> PortfolioBulkCascadeDeleteResponse:
    runtime = _get_runtime()
    response = _bulk_cascade_delete_portfolio_records(runtime.context, uids=uids)
    return PortfolioBulkCascadeDeleteResponse.model_validate(response)


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_portfolio_runtime

    return resolve_apps_v1_portfolio_runtime(
        models=[
            "Portfolio",
            "PortfolioDatasetAvailability",
            "Index",
            "Asset",
            "AssetSnapshotsStorage",
            "PortfolioMetadata",
            "SignalMetadata",
            "PortfolioWeightsStorage",
            "PortfoliosStorage",
            "SignalWeightsStorage",
            "TargetPositionsStorage",
            "VirtualFund",
            "VirtualFundHoldingsSet",
            "VirtualFundHoldingsStorage",
        ],
        row_model_name="GET /api/v1/portfolio/",
    )


def _list_portfolio_rows_response(context, **kwargs):
    from msm_portfolios.services import list_portfolio_rows_response

    return list_portfolio_rows_response(context, **kwargs)


def _get_portfolio_detail_response(context, **kwargs):
    from msm_portfolios.services import get_portfolio_detail_response

    return get_portfolio_detail_response(context, **kwargs)


def _get_portfolio_frontend_detail_summary(context, **kwargs):
    from msm_portfolios.services import get_portfolio_frontend_detail_summary

    return get_portfolio_frontend_detail_summary(context, **kwargs)


def _get_portfolio_weights_snapshot_response(context, **kwargs):
    from msm_portfolios.services import get_portfolio_weights_snapshot_response

    return get_portfolio_weights_snapshot_response(context, **kwargs)


def _get_portfolio_signal_weights_frame_response(context, **kwargs):
    from msm_portfolios.services import get_portfolio_signal_weights_frame_response

    return get_portfolio_signal_weights_frame_response(context, **kwargs)


def _get_portfolio_values_frame_response(context, **kwargs):
    from msm_portfolios.services import get_portfolio_values_frame_response

    return get_portfolio_values_frame_response(context, **kwargs)


def _delete_portfolio_record(context, **kwargs):
    from msm_portfolios.services import delete_portfolio_record

    return delete_portfolio_record(context, **kwargs)


def _cascade_delete_portfolio_record(context, **kwargs):
    from msm_portfolios.services import cascade_delete_portfolio_record

    return cascade_delete_portfolio_record(context, **kwargs)


def _delete_portfolio_weights(context, **kwargs):
    from msm_portfolios.services import delete_portfolio_weights

    return delete_portfolio_weights(context, **kwargs)


def _bulk_delete_portfolio_records(context, **kwargs):
    from msm_portfolios.services import bulk_delete_portfolio_records

    return bulk_delete_portfolio_records(context, **kwargs)


def _portfolio_delete_impact():
    from msm.models import PortfolioTable
    from msm.services import delete_rows_impact

    return delete_rows_impact(PortfolioTable)


def _portfolio_delete_preflight_item(
    context,
    *,
    uid: str,
) -> tuple[bool, list[str], list[str]]:
    from msm_portfolios.services import public_api

    existing = public_api._get_portfolio_row(context, uid=uid)
    if existing is None:
        return False, [], []
    portfolio = public_api._build_portfolio_row(existing)
    portfolio_uid = uuid.UUID(str(portfolio["uid"]))
    portfolio_identifier = str(portfolio.get("unique_identifier") or "")
    blockers = public_api._portfolio_delete_blockers(context, portfolio_uid=portfolio_uid)
    retained = public_api._retained_portfolio_datasets(
        public_api._portfolio_dataset_tables(context, portfolio_identifier=portfolio_identifier),
        portfolio_uid=portfolio_uid,
        portfolio_identifier=portfolio_identifier,
    )
    warnings = [
        f"its {item['dataset']} rows in table {item['meta_table_uid']} stay in place; "
        "the application that owns that table deletes them."
        for item in retained
    ]
    return True, blockers, warnings


def _bulk_cascade_delete_portfolio_records(context, **kwargs):
    from msm_portfolios.services import bulk_cascade_delete_portfolio_records

    return bulk_cascade_delete_portfolio_records(context, **kwargs)


def _validate_portfolio_row(row: object) -> Portfolio:
    if isinstance(row, Mapping):
        calendar_uid = row.get("calendar_uid")
        uid = row.get("uid")
        unique_identifier = row.get("unique_identifier")
    else:
        calendar_uid = getattr(row, "calendar_uid", None)
        uid = getattr(row, "uid", None)
        unique_identifier = getattr(row, "unique_identifier", None)

    if calendar_uid in (None, ""):
        row_label = unique_identifier or uid or "<unknown>"
        raise PortfolioDataIntegrityError(
            "Stored Portfolio row "
            f"{row_label!r} has calendar_uid=NULL, which violates the current "
            "PortfolioTable contract. Backfill calendar_uid to a persisted "
            "CalendarTable.uid before using the portfolio API."
        )
    return Portfolio.model_validate(row)
