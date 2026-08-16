from api.main import app as deployment_app
from apps.v1.main import app as application_app


def test_deployment_entrypoint_exposes_apps_v1_application() -> None:
    assert deployment_app is application_app
