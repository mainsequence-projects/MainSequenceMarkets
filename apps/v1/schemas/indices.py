from __future__ import annotations

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _index_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.indices import Index

    return Index


Index = _index_contract()
