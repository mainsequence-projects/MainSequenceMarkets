from __future__ import annotations

from apps.v1.schemas.indices import IndexListRow, IndexRecord


def list_indices(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[IndexListRow]:
    runtime = _get_runtime()
    rows = _list_index_catalog_rows(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [IndexListRow.model_validate(row) for row in rows]


def get_index(*, uid: str) -> IndexRecord | None:
    runtime = _get_runtime()
    record = _get_index_record(runtime.context, uid=uid)
    if record is None:
        return None
    return IndexRecord.model_validate(record)


def delete_index(*, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_index_record(runtime.context, uid=uid))


def _get_runtime():
    from msm.bootstrap import resolve_runtime
    from msm.models import IndexTable

    return resolve_runtime(
        models=[IndexTable],
        row_model_name="Index apps/v1",
    )


def _list_index_catalog_rows(context, **kwargs):
    from msm.services import list_index_catalog_rows

    return list_index_catalog_rows(context, **kwargs)


def _get_index_record(context, **kwargs):
    from msm.services import get_index_record

    return get_index_record(context, **kwargs)


def _delete_index_record(context, **kwargs):
    from msm.services import delete_index_record

    return delete_index_record(context, **kwargs)
