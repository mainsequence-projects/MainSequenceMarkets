from __future__ import annotations

import pytest

from scripts.bootstrap_metatables_access import (
    DeploymentWorkloads,
    deployment_workloads,
    team_name,
    with_team_writer,
)

TEAM = "4d2b8f6e-1c3a-4e5f-9b7d-0a2c4e6f8b19"
OTHER_TEAM = "7a9c1e3f-5b2d-4f6a-8c0e-2d4f6a8c0e31"
USER = "2e4a6c8e-0b1d-4f3a-9c5e-7d9f1b3d5f42"


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ("development", "ms-markets-development"),
        ("Production", "ms-markets-production"),
        (" Staging EU ", "ms-markets-staging-eu"),
    ],
)
def test_team_name_is_derived_from_the_environment(environment: str, expected: str) -> None:
    assert team_name(environment) == expected


def test_team_name_rejects_an_environment_without_letters_or_digits() -> None:
    with pytest.raises(ValueError, match="empty Team name"):
        team_name(" - ")


def test_deployment_workloads_come_from_the_deployment_workflow() -> None:
    assert deployment_workloads() == DeploymentWorkloads(
        job_name="ms-markets migrations",
        release_name="api",
    )


def test_with_team_writer_adds_the_team_and_keeps_other_grants() -> None:
    assignments = {
        "view": {"users": [USER], "teams": [OTHER_TEAM]},
        "edit": {"users": [USER], "teams": []},
    }

    assert with_team_writer(assignments, TEAM) == {
        "view": {"users": [USER], "teams": sorted([OTHER_TEAM, TEAM])},
        "edit": {"users": [USER], "teams": [TEAM]},
    }


def test_with_team_writer_promotes_a_reader_team() -> None:
    assignments = {"view": {"users": [], "teams": [TEAM]}, "edit": {"users": [], "teams": []}}

    assert with_team_writer(assignments, TEAM) == {
        "view": {"users": [], "teams": [TEAM]},
        "edit": {"users": [], "teams": [TEAM]},
    }


def test_with_team_writer_changes_nothing_when_the_team_is_already_writer() -> None:
    assignments = {"view": {"users": [], "teams": [TEAM]}, "edit": {"users": [], "teams": [TEAM]}}

    assert with_team_writer(assignments, TEAM) is None
