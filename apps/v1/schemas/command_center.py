from __future__ import annotations

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _command_center_data_contracts():
    prepare_apps_v1_import_namespace()
    from mainsequence.client.command_center.data_models import (
        TabularFrameFieldResponse,
        TabularFrameResponse,
        TabularFrameSourceResponse,
    )

    return TabularFrameFieldResponse, TabularFrameResponse, TabularFrameSourceResponse


TabularFrameFieldResponse, TabularFrameResponse, TabularFrameSourceResponse = (
    _command_center_data_contracts()
)
