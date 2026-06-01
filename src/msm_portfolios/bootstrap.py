from __future__ import annotations

from collections.abc import Mapping, Sequence

from msm.bootstrap import (
    MarketsRuntime,
    attach_schemas as _attach_schemas,
    get_runtime as _get_runtime,
    start_engine as _start_engine,
)
from msm.models.registration import MarketsModelSelector

from msm_portfolios.models import portfolio_sqlalchemy_models


def start_engine(
    *,
    data_source_uid: str | None = None,
    management_mode: str = "platform_managed",
    namespace: str | None = None,
    models: Sequence[MarketsModelSelector] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_identifier: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Bootstrap the portfolio runtime through the shared markets catalog."""

    return _start_engine(
        data_source_uid=data_source_uid,
        management_mode=management_mode,  # type: ignore[arg-type]
        namespace=namespace,
        models=resolve_portfolio_models(models),
        open_for_everyone=open_for_everyone,
        protect_from_deletion=protect_from_deletion,
        introspect=introspect,
        storage_hash_by_identifier=storage_hash_by_identifier,
        timeout=timeout,
    )


def attach_schemas(
    *,
    data_source_uid: str | None = None,
    management_mode: str = "platform_managed",
    namespace: str | None = None,
    models: Sequence[MarketsModelSelector] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Attach portfolio schemas through the shared markets runtime."""

    return _attach_schemas(
        data_source_uid=data_source_uid,
        management_mode=management_mode,  # type: ignore[arg-type]
        namespace=namespace,
        models=resolve_portfolio_models(models),
        timeout=timeout,
    )


def get_runtime() -> MarketsRuntime:
    return _get_runtime()


def resolve_portfolio_models(
    models: Sequence[MarketsModelSelector] | None = None,
) -> list[MarketsModelSelector]:
    if models is None:
        return list(portfolio_sqlalchemy_models())
    return [_resolve_portfolio_model(model) for model in models]


def _resolve_portfolio_model(model: MarketsModelSelector) -> MarketsModelSelector:
    if isinstance(model, type):
        return model

    model_key = str(model)
    for candidate in portfolio_sqlalchemy_models():
        keys = {
            candidate.__name__,
            str(getattr(candidate, "__markets_base_identifier__", "")),
            str(getattr(candidate, "__metatable_identifier__", "")),
        }
        if model_key in keys:
            return candidate
    return model


__all__ = [
    "MarketsRuntime",
    "attach_schemas",
    "get_runtime",
    "resolve_portfolio_models",
    "start_engine",
]
