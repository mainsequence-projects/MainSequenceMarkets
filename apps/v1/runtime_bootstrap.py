from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

V1_RUNTIME_MODELS = [
    "Asset",
    "OpenFigiAssetDetails",
    "AssetCategory",
    "AssetCategoryMembership",
    "IndexType",
    "Index",
]
_BOOTSTRAP_COMPLETE = False


def ensure_apps_v1_runtime() -> Any | None:
    global _BOOTSTRAP_COMPLETE

    if _BOOTSTRAP_COMPLETE:
        return None

    namespace = os.getenv("MSM_AUTO_REGISTER_NAMESPACE")
    if not namespace:
        return None

    import msm

    runtime = msm.start_engine(
        namespace=namespace,
        models=V1_RUNTIME_MODELS,
    )
    _BOOTSTRAP_COMPLETE = True
    return runtime


def resolve_apps_v1_runtime(
    *,
    models: Sequence[Any],
    row_model_name: str,
):
    ensure_apps_v1_runtime()

    from msm.bootstrap import resolve_runtime

    return resolve_runtime(
        models=models,
        row_model_name=row_model_name,
    )


__all__ = [
    "V1_RUNTIME_MODELS",
    "ensure_apps_v1_runtime",
    "resolve_apps_v1_runtime",
]
