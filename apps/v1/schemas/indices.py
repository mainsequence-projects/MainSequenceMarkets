from __future__ import annotations

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _contracts():
    prepare_apps_v1_import_namespace()
    from msm.api.indices import Index, IndexCreate, IndexType, IndexUpdate
    from msm.services.indices.contracts import (
        IndexDatasetDescriptor,
        IndexDatasetState,
        IndexDatasetSummary,
        IndexFormulaDetail,
        IndexFormulaSummary,
        RelatedMetaTable,
    )

    return (
        Index,
        IndexCreate,
        IndexUpdate,
        IndexType,
        IndexFormulaSummary,
        IndexFormulaDetail,
        IndexDatasetDescriptor,
        IndexDatasetState,
        IndexDatasetSummary,
        RelatedMetaTable,
    )


(
    Index,
    IndexCreate,
    IndexUpdate,
    IndexType,
    IndexFormulaSummary,
    IndexFormulaDetail,
    IndexDatasetDescriptor,
    IndexDatasetState,
    IndexDatasetSummary,
    RelatedMetaTable,
) = _contracts()
