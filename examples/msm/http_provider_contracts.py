"""Build provider-neutral HTTP discovery and an observable operation."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    _DIRECTORY = Path(__file__).resolve().parent
    # Run by path, this directory is on sys.path, and its platform/ hides the standard module.
    sys.path[:] = [entry for entry in sys.path if Path(entry).resolve() != _DIRECTORY]
    sys.path.insert(0, str(_DIRECTORY.parents[1] / "src"))

from pydantic import BaseModel  # noqa: E402

from msm.api.http import (  # noqa: E402
    InMemoryOperationStore,
    build_resource_discovery_spec,
    resource_column,
)


class RegistrationRequest(BaseModel):
    symbols: list[str]


def build_example() -> dict[str, object]:
    discovery = build_resource_discovery_spec(
        resource_id="assets",
        label="Assets",
        item_label="assets",
        identity_fields=("uid",),
        columns=(
            resource_column("unique_identifier", "Identifier", importance="primary"),
            resource_column("asset_type", "Asset type"),
        ),
        search=True,
    )
    operations = InMemoryOperationStore[RegistrationRequest, dict[str, int]]()
    operation = operations.create(
        action="register",
        request=RegistrationRequest(symbols=["BTCUSDT"]),
        owner_uid="example-user",
        steps=[("register", "Register assets")],
    )
    return {
        "discovery": discovery.response.model_dump(mode="json"),
        "operation": operation.model_dump(mode="json"),
    }


if __name__ == "__main__":
    print(build_example())
