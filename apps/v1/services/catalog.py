from __future__ import annotations

from apps.v1.schemas.catalog import (
    CatalogDeleteResponse,
    CatalogListResponse,
    CatalogRowsResponse,
)


class CatalogNotFoundError(LookupError):
    """Raised when the requested catalogue entry does not exist."""


class CatalogUnsupportedError(RuntimeError):
    """Raised when a catalogue entry cannot be served by this API."""


def list_catalogs(
    *,
    search: str = "",
    limit: int = 25,
    offset: int = 0,
) -> CatalogListResponse:
    context = _get_catalog_context()
    response = _list_catalog_tables(
        context,
        search=search,
        limit=limit,
        offset=offset,
    )
    return CatalogListResponse.model_validate(response)


def list_catalog_rows(
    *,
    catalog_uid: str,
    search: str = "",
    limit: int = 25,
    offset: int = 0,
) -> CatalogRowsResponse:
    context = _get_catalog_context()
    try:
        response = _list_catalog_table_rows(
            context,
            catalog_uid=catalog_uid,
            search=search,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        _raise_catalog_boundary_exception(exc)
        raise
    return CatalogRowsResponse.model_validate(response)


def delete_catalog_row(
    *,
    catalog_uid: str,
    uid: str,
) -> CatalogDeleteResponse:
    context = _get_catalog_context()
    try:
        response = _delete_catalog_table_row(
            context,
            catalog_uid=catalog_uid,
            uid=uid,
        )
    except Exception as exc:
        _raise_catalog_boundary_exception(exc)
        raise
    return CatalogDeleteResponse.model_validate(response)


def _get_catalog_context():
    from apps.v1.runtime_bootstrap import ensure_apps_v1_runtime
    from msm.services import catalog_repository_context

    ensure_apps_v1_runtime()
    return catalog_repository_context()


def _list_catalog_tables(context, **kwargs):
    from msm.services import list_catalog_tables

    return list_catalog_tables(context, **kwargs)


def _list_catalog_table_rows(context, **kwargs):
    from msm.services import list_catalog_table_rows

    return list_catalog_table_rows(context, **kwargs)


def _delete_catalog_table_row(context, **kwargs):
    from msm.services import delete_catalog_table_row

    return delete_catalog_table_row(context, **kwargs)


def _raise_catalog_boundary_exception(exc: Exception) -> None:
    from msm.services.catalog import CatalogTableNotFoundError, CatalogTableUnsupportedError

    if isinstance(exc, CatalogTableNotFoundError):
        raise CatalogNotFoundError(str(exc)) from exc
    if isinstance(exc, CatalogTableUnsupportedError):
        raise CatalogUnsupportedError(str(exc)) from exc
