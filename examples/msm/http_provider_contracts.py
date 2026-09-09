"""Build provider-neutral HTTP discovery and an observable operation."""

from __future__ import annotations

from pydantic import BaseModel

from msm.api.http import (
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
