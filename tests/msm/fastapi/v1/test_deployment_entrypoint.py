from pathlib import Path

import yaml

from api.main import app as deployment_app
from apps.v1.main import app as application_app


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def test_deployment_entrypoint_exposes_apps_v1_application() -> None:
    assert deployment_app is application_app


def test_main_fastapi_workflow_uses_current_automatic_deployment_contract() -> None:
    workflow_path = PROJECT_ROOT / ".mainsequence" / "workflows" / "fastapi.yaml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert workflow["api_version"] == "2.1.0"
    assert workflow["name"] == "mainsequence-markets-fastapi"

    resources = workflow["resources"]
    assert len(resources) == 1
    release = resources[0]
    assert release["key"] == "markets-api"
    assert release["kind"] == "resource_release"

    spec = release["spec"]
    assert spec["release_kind"] == "fastapi"
    assert spec["cors_allowed_origins"] == [
        "https://*.site-dev.main-sequence.app"
    ]
    assert spec["automatic_redeployment"] == {
        "enabled": True,
        "tag_regex": None,
    }
    assert spec["revision_retention_count"] == 3
    assert "related_image_uid" not in spec
