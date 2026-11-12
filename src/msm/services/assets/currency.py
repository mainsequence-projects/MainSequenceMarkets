"""Currency assets and the asset-type rule they share with registration (ADR 0051)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from msm.constants import ASSET_TYPE_CURRENCY

if TYPE_CHECKING:
    from msm.repositories import MarketsOperationContext


class AssetTypeConflictError(ValueError):
    """An existing asset's ``asset_type`` differs from the one a write requires.

    An existing asset keeps its type (ADR 0051, decision 7). The write is refused and
    nothing is written; the Markets API answers ``409``.
    """


def get_or_create_currency_asset(
    context: "MarketsOperationContext",
    *,
    code: str,
) -> dict[str, Any]:
    """Return the currency asset ``code``, creating it and the ``currency`` type if missing.

    One MetaTables operation. Built-in asset types are not seeded by the migrations, so
    ``ASSET_TYPE_CURRENCY_DEFINITION`` is created first when it is missing; an existing
    asset type or asset is not changed. Raises ``AssetTypeConflictError`` when ``code``
    is an existing asset of another type.
    """

    from msm.api.base import operation_result_rows
    from msm.repositories.asset_registration import (
        get_or_create_currency_asset as run_get_or_create,
    )

    identifier = str(code or "").strip()
    rows = operation_result_rows(run_get_or_create(context, code=identifier))
    if not rows:
        raise AssetTypeConflictError(
            f"Asset {identifier!r} exists with an asset_type other than {ASSET_TYPE_CURRENCY!r}."
        )
    return dict(rows[0])


__all__ = ["AssetTypeConflictError", "get_or_create_currency_asset"]
