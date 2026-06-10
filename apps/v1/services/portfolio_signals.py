from __future__ import annotations

import datetime as dt

from apps.v1.schemas.portfolio_signals import (
    PortfolioSignalDeleteResponse,
    PortfolioSignalListResponse,
    PortfolioSignalWeightsDeleteResponse,
    SignalMetadata,
    SignalMetadataCreate,
    SignalMetadataUpdate,
)


class PortfolioSignalDeleteConflictError(ValueError):
    """Raised when signal metadata cannot be deleted because protected rows remain."""


def list_portfolio_signals(
    *,
    search: str = "",
    signal_uid: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> PortfolioSignalListResponse:
    runtime = _get_runtime()
    response = _list_signal_metadata_response(
        runtime.context,
        search=search,
        signal_uid=signal_uid,
        limit=limit,
        offset=offset,
    )
    return PortfolioSignalListResponse.model_validate(response)


def get_portfolio_signal(*, uid: str) -> SignalMetadata | None:
    runtime = _get_runtime()
    response = _get_signal_metadata_response(runtime.context, uid=uid)
    if response is None:
        return None
    return SignalMetadata.model_validate(response)


def create_portfolio_signal(*, payload: SignalMetadataCreate) -> SignalMetadata:
    runtime = _get_runtime()
    response = _create_signal_metadata_response(
        runtime.context,
        **payload.model_dump(),
    )
    return SignalMetadata.model_validate(response)


def update_portfolio_signal(
    *,
    uid: str,
    payload: SignalMetadataUpdate,
) -> SignalMetadata | None:
    runtime = _get_runtime()
    response = _update_signal_metadata_response(
        runtime.context,
        uid=uid,
        **payload.model_dump(),
    )
    if response is None:
        return None
    return SignalMetadata.model_validate(response)


def delete_portfolio_signal(*, uid: str) -> PortfolioSignalDeleteResponse | None:
    runtime = _get_runtime()
    try:
        response = _delete_signal_metadata_record(runtime.context, uid=uid)
    except Exception as exc:
        if _is_signal_delete_conflict(exc):
            raise PortfolioSignalDeleteConflictError(str(exc)) from exc
        raise
    if response is None:
        return None
    return PortfolioSignalDeleteResponse.model_validate(response)


def delete_portfolio_signal_weights(
    *,
    uid: str,
    weights_date: dt.datetime | None = None,
) -> PortfolioSignalWeightsDeleteResponse | None:
    runtime = _get_runtime()
    response = _delete_signal_weights(runtime.context, uid=uid, weights_date=weights_date)
    if response is None:
        return None
    return PortfolioSignalWeightsDeleteResponse.model_validate(response)


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_portfolio_runtime

    return resolve_apps_v1_portfolio_runtime(
        models=[
            "Asset",
            "SignalMetadata",
            "SignalWeightsStorage",
        ],
        row_model_name="GET /api/v1/portfolio-signal/",
    )


def _list_signal_metadata_response(context, **kwargs):
    from msm_portfolios.services import list_signal_metadata_response

    return list_signal_metadata_response(context, **kwargs)


def _get_signal_metadata_response(context, **kwargs):
    from msm_portfolios.services import get_signal_metadata_response

    return get_signal_metadata_response(context, **kwargs)


def _create_signal_metadata_response(context, **kwargs):
    from msm_portfolios.services import create_signal_metadata_response

    return create_signal_metadata_response(context, **kwargs)


def _update_signal_metadata_response(context, **kwargs):
    from msm_portfolios.services import update_signal_metadata_response

    return update_signal_metadata_response(context, **kwargs)


def _delete_signal_metadata_record(context, **kwargs):
    from msm_portfolios.services import delete_signal_metadata_record

    return delete_signal_metadata_record(context, **kwargs)


def _delete_signal_weights(context, **kwargs):
    from msm_portfolios.services import delete_signal_weights

    return delete_signal_weights(context, **kwargs)


def _is_signal_delete_conflict(exc: Exception) -> bool:
    from msm_portfolios.services import SignalDeleteConflictError

    return isinstance(exc, SignalDeleteConflictError)
