"""Virtual-fund allocation policies: described, versioned functions of units (ADR 0053).

A policy takes the account's holdings and each fund's unit basket, both as signed
quantities (quantity times direction), and answers the split in units. It reads no
storage and no price.

Each policy is described from its ``Arguments`` class, and a request's arguments
are validated with the same class, so the description cannot drift from what runs.
A change to an argument, a bound, a default or a behaviour bumps ``version``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_NULL = {"type": "null"}

FundId = Hashable
AssetId = Hashable


class AllocationError(ValueError):
    """An allocation request that cannot be planned or applied.

    ``code`` is the machine-readable reason the Markets API answers with, and
    ``status_code`` its HTTP status. ``errors`` lists each offending input.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.errors = list(errors or [])


@dataclass(frozen=True, slots=True)
class Allocation:
    """The split of one snapshot between the funds and the direct sleeve, in units.

    ``fills`` is what each fund gets of each asset it claims, and ``direct`` what
    stays in the account. For every asset, the fills and the direct quantity add up
    to the holding.
    """

    fills: Mapping[tuple[FundId, AssetId], float]
    direct: Mapping[AssetId, float]


def proportional_attribution(
    holdings: Mapping[AssetId, float],
    targets: Mapping[tuple[FundId, AssetId], float],
    *,
    quantity_tolerance: float = 1e-9,
) -> Allocation:
    """Fill every fund's claim on an asset in the same proportion, capped at one.

    ``holdings`` and ``targets`` are signed quantities: quantity times direction.
    For each asset the proportion is the holding's size divided by the funds'
    total claims on it. A fill keeps its claim's side. What the funds do not take
    stays in the direct sleeve. A fill at or below ``quantity_tolerance`` is
    dropped, and its units stay direct. The result can always be applied.
    """

    # One pass per input, whatever the number of funds and assets: the claims per
    # asset, the fills, then the direct sleeve.
    gross: dict[AssetId, float] = {}
    for (_fund, asset), claim in targets.items():
        gross[asset] = gross.get(asset, 0.0) + abs(float(claim))

    scale = {
        asset: min(1.0, abs(float(holdings.get(asset, 0.0))) / total) if total > 0 else 0.0
        for asset, total in gross.items()
    }

    fills: dict[tuple[FundId, AssetId], float] = {}
    taken: dict[AssetId, float] = dict.fromkeys(gross, 0.0)
    for key, claim in targets.items():
        asset = key[1]
        fill = float(claim) * scale[asset]
        if abs(fill) <= quantity_tolerance:
            fill = 0.0
        fills[key] = fill
        taken[asset] += fill

    direct = {asset: float(held) - taken.get(asset, 0.0) for asset, held in holdings.items()}
    for asset, quantity in taken.items():
        if asset not in direct:
            direct[asset] = -quantity
    return Allocation(fills=fills, direct=direct)


class ProportionalAttributionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", title="Proportional attribution arguments")

    quantity_tolerance: float = Field(
        default=1e-9,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        title="Quantity tolerance",
        description=(
            "An absolute quantity in each asset's own unit. A fill at or below it is not "
            "written, and a direct line at or below it is left out."
        ),
    )


AllocationFunction = Callable[..., Allocation]


@dataclass(frozen=True)
class AllocationPolicyDefinition:
    """One allocation policy as the registry lists it."""

    id: str
    version: str
    title: str
    description: str
    Arguments: type[BaseModel]
    allocate: AllocationFunction


ALLOCATION_POLICIES: tuple[AllocationPolicyDefinition, ...] = (
    AllocationPolicyDefinition(
        id="proportional_attribution",
        version="1.0.0",
        title="Proportional attribution",
        description=(
            "Every fund's claim on an asset is filled in the same proportion: the account's "
            "holding of the asset divided by the funds' total claims on it, capped at one. A "
            "claim the holding cannot cover keeps the shortfall as a positive delta, and the plan stays "
            "usable. What the funds do not take stays in the direct account sleeve. Nothing is "
            "traded, borrowed or bought."
        ),
        Arguments=ProportionalAttributionArguments,
        allocate=proportional_attribution,
    ),
)
_BY_ID = {policy.id: policy for policy in ALLOCATION_POLICIES}

DEFAULT_ALLOCATION_POLICY_ID = "proportional_attribution"


def allocation_policy(policy_id: str) -> AllocationPolicyDefinition | None:
    return _BY_ID.get(policy_id)


class AllocationPolicyChoice(BaseModel):
    """The policy a request runs: its id, the version it was built against, and arguments."""

    model_config = ConfigDict(extra="forbid")

    DEFAULT_ID: ClassVar[str] = DEFAULT_ALLOCATION_POLICY_ID

    id: str = Field(
        min_length=1,
        description="A policy id, as `getVirtualFundAllocationPolicies` lists it.",
    )
    version: str = Field(
        min_length=1,
        description=(
            "The policy version the request was built against. Any other version than the "
            "registry's answers 409 `policy_version_mismatch`."
        ),
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="The policy's arguments, validated against its `arguments_schema`.",
    )


@dataclass(frozen=True)
class ResolvedAllocationPolicy:
    """A validated policy choice: the definition and its arguments with defaults filled in."""

    definition: AllocationPolicyDefinition
    arguments: Mapping[str, Any]

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def version(self) -> str:
        return self.definition.version

    @property
    def quantity_tolerance(self) -> float:
        return float(self.arguments.get("quantity_tolerance", 0.0))

    def allocate(
        self,
        holdings: Mapping[AssetId, float],
        targets: Mapping[tuple[FundId, AssetId], float],
    ) -> Allocation:
        return self.definition.allocate(holdings, targets, **self.arguments)

    def as_choice(self) -> dict[str, Any]:
        return {"id": self.id, "version": self.version, "arguments": dict(self.arguments)}


def default_allocation_policy_choice() -> AllocationPolicyChoice:
    definition = _BY_ID[DEFAULT_ALLOCATION_POLICY_ID]
    return AllocationPolicyChoice(id=definition.id, version=definition.version)


def resolve_allocation_policy(
    choice: AllocationPolicyChoice | Mapping[str, Any],
) -> ResolvedAllocationPolicy:
    """Validate a policy choice against the registry.

    Raises ``AllocationError``: ``not_found`` for an unknown id,
    ``policy_version_mismatch`` for another version, and
    ``invalid_policy_arguments`` for arguments that break the policy's schema.
    """

    try:
        request = (
            choice
            if isinstance(choice, AllocationPolicyChoice)
            else AllocationPolicyChoice.model_validate(dict(choice))
        )
    except ValidationError as exc:
        raise AllocationError(
            "invalid_policy_arguments",
            "The policy must name an id and a version.",
            errors=_validation_errors(exc),
        ) from exc
    definition = _BY_ID.get(request.id)
    if definition is None:
        raise AllocationError(
            "not_found",
            f"No allocation policy has the id {request.id!r}.",
            status_code=404,
        )
    if request.version != definition.version:
        raise AllocationError(
            "policy_version_mismatch",
            f"Policy {definition.id!r} is at version {definition.version}; the request was "
            f"built against {request.version}.",
            status_code=409,
        )
    try:
        arguments = definition.Arguments.model_validate(request.arguments)
    except ValidationError as exc:
        raise AllocationError(
            "invalid_policy_arguments",
            f"The arguments break the description of policy {definition.id!r}.",
            errors=_validation_errors(exc),
        ) from exc
    return ResolvedAllocationPolicy(definition=definition, arguments=arguments.model_dump())


def _validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Each error's input and message; never the value that was sent."""

    return [
        {
            "input": ".".join(str(part) for part in error.get("loc", ())) or "policy",
            "message": str(error.get("msg", "")).removeprefix("Value error, "),
        }
        for error in exc.errors()
    ]


def _resolve_schema(node: Any, defs: Mapping[str, Any]) -> Any:
    """Inline ``$ref``s and drop the null branch of optional values."""

    if isinstance(node, list):
        return [_resolve_schema(item, defs) for item in node]
    if not isinstance(node, dict):
        return node
    reference = node.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        target = _resolve_schema(defs[reference.removeprefix("#/$defs/")], defs)
        siblings = {key: _resolve_schema(value, defs) for key, value in node.items() if key != "$ref"}
        return {**target, **siblings}
    resolved = {key: _resolve_schema(value, defs) for key, value in node.items() if key != "$defs"}
    branches = resolved.get("anyOf")
    if isinstance(branches, list) and _NULL in branches:
        others = [branch for branch in branches if branch != _NULL]
        if len(others) == 1:
            resolved.pop("anyOf")
            resolved = {**others[0], **resolved}
            if "default" in resolved and resolved["default"] is None:
                resolved.pop("default")
    return resolved


def describe_allocation_policy(definition: AllocationPolicyDefinition) -> dict[str, Any]:
    """Describe a policy: each argument's JSON Schema 2020-12, generated from ``Arguments``."""

    schema = definition.Arguments.model_json_schema()
    defs = schema.get("$defs", {})
    required = set(schema.get("required", ()))
    arguments: dict[str, dict[str, Any]] = {}
    properties: dict[str, Any] = {}
    for name, prop in schema.get("properties", {}).items():
        fragment = _resolve_schema(dict(prop), defs)
        properties[name] = fragment
        arguments[name] = {
            "title": fragment.get("title", name),
            "description": fragment.get("description", ""),
            "required": name in required,
            "schema": {"$schema": SCHEMA_DIALECT, **fragment},
        }
    return {
        "id": definition.id,
        "version": definition.version,
        "title": definition.title,
        "description": definition.description,
        "arguments": arguments,
        "arguments_schema": {
            "$schema": SCHEMA_DIALECT,
            "title": schema.get("title", f"{definition.title} arguments"),
            "type": "object",
            "properties": properties,
            "required": sorted(required),
            "additionalProperties": False,
        },
    }


def allocation_policy_summary(definition: AllocationPolicyDefinition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "version": definition.version,
        "title": definition.title,
        "description": definition.description,
    }


__all__ = [
    "ALLOCATION_POLICIES",
    "DEFAULT_ALLOCATION_POLICY_ID",
    "SCHEMA_DIALECT",
    "Allocation",
    "AllocationError",
    "AllocationPolicyChoice",
    "AllocationPolicyDefinition",
    "ProportionalAttributionArguments",
    "ResolvedAllocationPolicy",
    "allocation_policy",
    "allocation_policy_summary",
    "default_allocation_policy_choice",
    "describe_allocation_policy",
    "proportional_attribution",
    "resolve_allocation_policy",
]
