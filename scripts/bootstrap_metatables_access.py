"""Give the ms-markets deployment Writer access to its MetaTables namespace in one Environment.

The deployment's migration Job and FastAPI release run as their own workload
Users. Those start with no MetaTables grants, and a deployment workflow cannot
declare one, so an Organization admin runs this once per Environment from a
checkout of the branch deployed there (`development` or `main`). Run it again
whenever the platform recreates one of those workloads. It:

1. creates or finds the Team `ms-markets-<environment>`, named from the
   checkout's Environment;
2. adds the workload Users of the migration Job and FastAPI release declared in
   `.mainsequence/workflows/ms-markets-api.yaml`;
3. creates the `mainsequence.markets` namespace in the Environment's MetaTables
   API if it does not exist;
4. grants the Team Writer on that namespace and keeps every other grant;
5. checks that each workload User has Writer on the provider's Alembic version
   table, once that table is registered.

Re-running changes nothing that is already in place. `--dry-run` reports what
would change without changing anything.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

PROJECT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT / ".mainsequence" / "workflows" / "ms-markets-api.yaml"
TEAM_PREFIX = "ms-markets-"


@dataclass(frozen=True)
class DeploymentWorkloads:
    """The workflow resources whose workload Users need MetaTables access."""

    job_name: str
    release_name: str


def deployment_workloads(workflow_path: Path = WORKFLOW) -> DeploymentWorkloads:
    """Read the migration Job name and FastAPI release name from the workflow."""

    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    resources = workflow["resources"]
    jobs = [resource for resource in resources if resource["kind"] == "job"]
    releases = [resource for resource in resources if resource["kind"] == "fastapi"]
    if len(jobs) != 1 or len(releases) != 1:
        raise ValueError(f"{workflow_path} must declare exactly one job and one fastapi resource.")
    # The platform names a FastAPI release after its source directory.
    return DeploymentWorkloads(
        job_name=jobs[0]["spec"]["name"],
        release_name=PurePosixPath(releases[0]["spec"]["source_path"]).parent.name,
    )


def team_name(environment_name: str) -> str:
    """Return `ms-markets-<environment>` for an Environment name such as `Production`."""

    slug = re.sub(r"[^a-z0-9]+", "-", environment_name.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"Environment name {environment_name!r} yields an empty Team name.")
    return TEAM_PREFIX + slug


def with_team_writer(assignments: dict[str, Any], team_uid: str) -> dict[str, Any] | None:
    """Return the grant assignments with the Team as Writer, or `None` when it already is.

    MetaTables replaces the whole assignment document on update, and every Writer
    must also be listed in `view`.
    """

    view_teams = set(assignments["view"]["teams"])
    edit_teams = set(assignments["edit"]["teams"])
    if team_uid in view_teams and team_uid in edit_teams:
        return None
    return {
        "view": {**assignments["view"], "teams": sorted(view_teams | {team_uid})},
        "edit": {**assignments["edit"], "teams": sorted(edit_teams | {team_uid})},
    }


class MetaTablesAdmin:
    """Admin calls to the MetaTables API of the checkout's Environment."""

    def __init__(self) -> None:
        from mainsequence.client.utils import make_request
        from metatables import MetaTable

        self._make_request = make_request
        self._session = MetaTable.build_session()
        self._loaders = MetaTable.LOADERS
        self.url = MetaTable.get_object_url().rstrip("/").rsplit("/", 1)[0]

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        response = self._make_request(
            s=self._session,
            loaders=self._loaders,
            r_type=method,
            url=f"{self.url}/{path}",
            payload=payload or {},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} failed with {response.status_code}: {response.text[:500]}")
        return response.json()

    def find_namespace(self, name: str) -> str | None:
        resources = self.request("GET", "security/resources/", {"params": {"search": name, "limit": 500}})
        matches = [row["uid"] for row in resources["namespaces"] if row["name"] == name]
        return matches[0] if matches else None

    def find_table(self, identifier: str, physical_table_name: str) -> str | None:
        # The admin listing searches physical table names and labels rows by identifier.
        resources = self.request(
            "GET", "security/resources/", {"params": {"search": physical_table_name, "limit": 500}}
        )
        matches = [row["uid"] for row in resources["tables"] if row["name"] in (identifier, physical_table_name)]
        return matches[0] if matches else None


def _workload_users(workloads: DeploymentWorkloads) -> tuple[dict[str, str], list[str]]:
    """Return the workload User UID of each deployed workload, and the workloads not deployed yet."""

    from mainsequence.client import Job, ResourceRelease

    found: dict[str, str] = {}
    missing: list[str] = []
    candidates = [
        (f"Job {workloads.job_name!r}", list(Job.filter(name=workloads.job_name))),
        (
            f"FastAPI release {workloads.release_name!r}",
            list(ResourceRelease.filter(name=workloads.release_name, release_kind="fastapi")),
        ),
    ]
    for label, rows in candidates:
        if len(rows) > 1:
            raise RuntimeError(f"{label} matches {len(rows)} objects on this branch.")
        if not rows or not rows[0].workload_user_uid:
            missing.append(label)
        else:
            found[label] = str(rows[0].workload_user_uid)
    return found, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without changing it.")
    args = parser.parse_args()

    from mainsequence.client import Team
    from mainsequence.code_repository_context import require_code_repository_branch_context
    from metatables.endpoint import api_endpoint_scope

    from msm.settings import DEFAULT_MARKETS_NAMESPACE, MSM_AUTO_REGISTER_NAMESPACE_ENV

    if os.environ.get(MSM_AUTO_REGISTER_NAMESPACE_ENV):
        print(f"Unset {MSM_AUTO_REGISTER_NAMESPACE_ENV}: the deployment uses {DEFAULT_MARKETS_NAMESPACE!r}.")
        return 2
    from msm_migrations import MarketsAlembicVersion

    dry_run = args.dry_run
    context = require_code_repository_branch_context("ms-markets MetaTables access bootstrap")
    environment_name = context.code_repository_branch.organization_environment_name
    team = team_name(environment_name)
    namespace = DEFAULT_MARKETS_NAMESPACE
    print(f"Branch {context.repository_branch!r} -> Environment {environment_name!r}")
    print(f"Team {team!r}, namespace {namespace!r}{' (dry run)' if dry_run else ''}")

    users, missing = _workload_users(deployment_workloads())
    for label, uid in users.items():
        print(f"  {label}: workload User {uid}")
    for label in missing:
        print(f"  {label}: not deployed on this branch yet; run this again after its first deployment")

    matches = [row for row in Team.filter(search=team) if row.name == team]
    if len(matches) > 1:
        raise RuntimeError(f"{len(matches)} Teams are named {team!r}; keep one.")
    team_row = matches[0] if matches else None
    if team_row is None:
        print(f"Create Team {team!r}")
        if not dry_run:
            team_row = Team.create(name=team, description=f"ms-markets deployment workloads in {environment_name}")
    members = {member.uid for member in team_row.list_members()} if team_row is not None else set()
    to_add = sorted(set(users.values()) - members)
    if to_add:
        print(f"Add to {team!r}: {', '.join(to_add)}")
        if not dry_run:
            team_row.add_members(to_add)

    with api_endpoint_scope():
        metatables = MetaTablesAdmin()
        print(f"MetaTables API: {metatables.url}")
        namespace_uid = metatables.find_namespace(namespace)
        if namespace_uid is None:
            print(f"Create namespace {namespace!r}")
            if not dry_run:
                namespace_uid = metatables.request("POST", "security/namespaces/", {"json": {"name": namespace}})["uid"]
        if namespace_uid is None or team_row is None:
            # Only a dry run gets here: the namespace or Team it would create does not exist yet.
            print(f"Grant {team!r} Writer on {namespace!r}")
        else:
            document = metatables.request("GET", f"namespaces/{namespace_uid}/permissions", {"params": {}})
            assignments = with_team_writer(document["assignments"], str(team_row.uid))
            if assignments is not None:
                print(f"Grant {team!r} Writer on {namespace!r}")
                if not dry_run:
                    metatables.request(
                        "PUT",
                        f"namespaces/{namespace_uid}/permissions",
                        {"json": {"assignments": assignments, "revision": document["revision"]}},
                    )

        identifier = MarketsAlembicVersion.__metatable_identifier__
        table_uid = metatables.find_table(identifier, MarketsAlembicVersion.__alembic_version_table_name__)
        if table_uid is None:
            print(f"{identifier!r} is not registered yet; the migration Job registers it under the namespace grant.")
        elif not dry_run:
            denied = []
            for label, uid in users.items():
                access = metatables.request(
                    "GET", f"meta-tables/{table_uid}/effective-access/", {"params": {"user_uid": uid}}
                )["effective_access"]
                print(f"  {label}: effective access on {identifier!r} = {access}")
                if access != "writer":
                    denied.append(label)
            if denied:
                print(f"Writer did not take effect for: {', '.join(denied)}")
                return 1

    if missing:
        return 1
    print("Done." if not dry_run else "Dry run: nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
