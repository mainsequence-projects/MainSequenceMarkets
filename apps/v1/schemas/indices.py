from __future__ import annotations

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _contracts():
    prepare_apps_v1_import_namespace()
    from msm.api.indices import Index, IndexCreate, IndexType, IndexUpdate
    from msm.services.indices.contracts import (
        IndexBulkDeleteExecuteRequest,
        IndexBulkDeletePreview,
        IndexBulkDeletePreviewRequest,
        IndexBulkDeleteResult,
        IndexDatasetDescriptor,
        IndexDatasetSummary,
        IndexMethodologyDetail,
        IndexMethodologySummary,
        IndexRelatedMetaTable,
    )

    return (
        Index,
        IndexCreate,
        IndexUpdate,
        IndexType,
        IndexMethodologySummary,
        IndexMethodologyDetail,
        IndexDatasetDescriptor,
        IndexDatasetSummary,
        IndexRelatedMetaTable,
        IndexBulkDeletePreviewRequest,
        IndexBulkDeletePreview,
        IndexBulkDeleteExecuteRequest,
        IndexBulkDeleteResult,
    )


(
    Index,
    IndexCreate,
    IndexUpdate,
    IndexType,
    IndexMethodologySummary,
    IndexMethodologyDetail,
    IndexDatasetDescriptor,
    IndexDatasetSummary,
    IndexRelatedMetaTable,
    IndexBulkDeletePreviewRequest,
    IndexBulkDeletePreview,
    IndexBulkDeleteExecuteRequest,
    IndexBulkDeleteResult,
) = _contracts()
