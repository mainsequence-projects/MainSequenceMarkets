from pathlib import Path

import yaml

from api.main import app as deployment_app
from apps.v1.main import app as application_app


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def test_deployment_entrypoint_exposes_apps_v1_application() -> None:
    assert deployment_app is application_app


def test_main_fastapi_workflow_uses_current_automatic_deployment_contract() -> None:
    workflow_path = PROJECT_ROOT / ".mainsequence" / "workflows" / "ms-markets-api.yaml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert workflow["api_version"] == "2.3.0"
    assert workflow["name"] == "mainsequence-markets-fastapi"

    resources = {resource["key"]: resource for resource in workflow["resources"]}
    assert set(resources) == {"markets-api", "migrate-markets"}
    release = resources["markets-api"]
    assert release["kind"] == "fastapi"

    spec = release["spec"]
    assert spec["source_path"] == "api/main.py"
    assert (PROJECT_ROOT / spec["source_path"]).is_file()
    assert spec["automatic_deployment"] is True
    assert spec["cors_allowed_origins"] == [
        "https://*.site-dev.main-sequence.app"
    ]
    assert spec["automatic_redeployment"] == {
        "enabled": True,
        "tag_regex": None,
    }
    assert spec["revision_retention_count"] == 3
    assert "related_image_uid" not in spec


def test_main_fastapi_workflow_migrates_before_the_api_deploys() -> None:
    workflow_path = PROJECT_ROOT / ".mainsequence" / "workflows" / "ms-markets-api.yaml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    job = next(resource for resource in workflow["resources"] if resource["key"] == "migrate-markets")
    assert job["kind"] == "job"
    assert job["spec"]["execution_path"] == "jobs/migrate_markets.py"
    assert job["spec"]["automatic_redeployment"] == {"enabled": True, "tag_regex": None}
    job_source = (PROJECT_ROOT / job["spec"]["execution_path"]).read_text(encoding="utf-8")
    assert "upgrade_application" in job_source
    assert '"msm_migrations:migration"' in job_source

    steps = workflow["execution"]["steps"]
    assert steps["image"] == {"prepare_image": "markets-api"}
    assert steps["migrate"] == {
        "run_job": "migrate-markets",
        "image_from": "image",
        "needs": ["image"],
    }
    assert steps["deploy_api"] == {
        "deploy": "markets-api",
        "image_from": "image",
        "needs": ["migrate"],
    }
