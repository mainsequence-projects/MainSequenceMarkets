"""Remote row operations for ``msm.client`` (ADR 0047, decision 2).

An application that selects the remote backend runs ``msm.api`` row class
methods (``Asset.upsert``, ``Portfolio.get_by_uid`` ...) here instead of
against MetaTables. ``POST /rows/{resource}/{operation}/`` runs exactly the
public class method ``operation`` of the row class registered as ``resource``,
on this deployment's runtime backend, with the JSON arguments the client sent,
and returns its result. The operations are the row classes' own public class
methods, so the remote and runtime backends cannot drift apart; there is no
generic query endpoint.

Writes go through ``registry_write``, so the registry write policy
(``apps.v1.policy``) applies to applications. ``delete`` runs the resource's
service delete, with its preflight checks, and is offered only where such a
service exists.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from apps.v1.identity import registry_write
from apps.v1.policy import RegistryWriteForbidden, RegistryWritePolicyError

router = APIRouter(prefix="/rows", tags=["rows"])


class RowOperationRequest(BaseModel):
    """The arguments of one row class method, as JSON."""

    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Named arguments of the class method. Pydantic payloads are sent as objects "
            "with only the fields that were set."
        ),
    )


class RowOperationResponse(BaseModel):
    """The JSON form of the class method's return value."""

    result: Any = None


class RowOperationDescription(BaseModel):
    name: str
    write: bool
    signature: str


class RowResourceDescription(BaseModel):
    resource: str
    row_class: str
    operations: list[RowOperationDescription]


def _load_row_classes() -> dict[str, type]:
    import msm.api.accounts  # noqa: F401
    import msm.api.assets  # noqa: F401
    import msm.api.calendars.core  # noqa: F401
    import msm.api.calendars.dates  # noqa: F401
    import msm.api.calendars.events  # noqa: F401
    import msm.api.calendars.sessions  # noqa: F401
    import msm.api.derivatives  # noqa: F401
    import msm.api.execution  # noqa: F401
    import msm.api.formula_indices  # noqa: F401
    import msm.api.indices  # noqa: F401
    import msm.api.issuers  # noqa: F401
    import msm.api.portfolios  # noqa: F401
    import msm.api.virtual_funds  # noqa: F401
    import msm_portfolios.api.market_metadata  # noqa: F401
    import msm_portfolios.api.portfolios  # noqa: F401
    import msm_pricing.api.curve_building_details  # noqa: F401
    import msm_pricing.api.curves  # noqa: F401
    import msm_pricing.api.index_convention_details  # noqa: F401
    import msm_pricing.api.market_data_bindings  # noqa: F401
    import msm_pricing.api.pricing_details  # noqa: F401
    from msm.api.remote import registered_row_classes

    return registered_row_classes()


def _service_deletes() -> dict[str, Callable[[str], Any]]:
    from apps.v1.services import asset_categories, assets, calendars, indices, portfolio_groups
    from apps.v1.services import portfolios

    return {
        "asset": lambda uid: assets.delete_asset(uid=uid),
        "asset-category": lambda uid: asset_categories.delete_asset_category(uid=uid),
        "calendar": lambda uid: calendars.delete_calendar(uid=uid),
        "index": lambda uid: indices.delete_index(uid=uid),
        "portfolio": lambda uid: portfolios.delete_portfolio(uid=uid),
        "portfolio-group": lambda uid: portfolio_groups.delete_portfolio_group(uid=uid),
    }


@router.get(
    "/",
    response_model=list[RowResourceDescription],
    summary="List remote row operations",
    description=(
        "List every row resource and the class methods `msm.client` may run on it. "
        "Each operation is `POST /rows/{resource}/{operation}/`."
    ),
    operation_id="describeRowOperations",
)
def describe_row_operations() -> list[RowResourceDescription]:
    from msm.api.remote import WRITE_OPERATIONS, remote_operations

    deletes = _service_deletes()
    described: list[RowResourceDescription] = []
    for resource, cls in sorted(_load_row_classes().items()):
        operations = [
            RowOperationDescription(
                name=name,
                write=name in WRITE_OPERATIONS,
                signature=str(inspect.signature(func)).replace("cls, ", "", 1),
            )
            for name, func in sorted(remote_operations(cls).items())
            if name != "delete" or resource in deletes or _owns_checked_delete(cls)
        ]
        described.append(
            RowResourceDescription(resource=resource, row_class=cls.__name__, operations=operations)
        )
    return described


@router.post(
    "/{resource}/{operation}/",
    response_model=RowOperationResponse,
    summary="Run a remote row operation",
    description=(
        "Run one public class method of a Markets row class on this deployment and return "
        "its result. Used by `msm.client`'s remote backend; see `describeRowOperations` for the "
        "available operations. Writes are subject to the registry write policy."
    ),
    operation_id="runRowOperation",
    responses={
        400: {"description": "The arguments were invalid (`ValueError` or `TypeError`)."},
        403: {"description": "The registry write policy refused this application."},
        404: {"description": "Unknown resource or operation, or the row was not found."},
        409: {"description": "The operation conflicted with existing rows."},
        501: {"description": "The operation is not offered remotely."},
    },
)
def run_row_operation(
    resource: str,
    operation: str,
    request: RowOperationRequest,
) -> RowOperationResponse | JSONResponse:
    from msm.api.remote import (
        WRITE_OPERATIONS,
        decode_arguments,
        encode_result,
        remote_operations,
        runtime_backend_only,
    )

    cls = _load_row_classes().get(resource)
    if cls is None:
        return _error(404, f"Unknown row resource {resource!r}.", "LookupError")

    if operation == "delete" and not _owns_checked_delete(cls):
        delete = _service_deletes().get(resource)
        if delete is None:
            return _error(
                501,
                f"{cls.__name__}.delete is not offered remotely; use the {resource} service "
                "routes, which run its delete preflight.",
                "NotImplementedError",
            )
        uid = str(request.arguments.get("uid") or "")
        if not uid:
            return _error(400, "delete requires a uid.", "ValueError")
        return _run(lambda: _deleted(delete(uid), uid), encode_result)

    operations = remote_operations(cls)
    if operation not in operations:
        return _error(404, f"{cls.__name__} has no remote operation {operation!r}.", "LookupError")

    try:
        arguments = decode_arguments(cls, operation, request.arguments)
    except (TypeError, ValueError) as exc:
        return _error(400, str(exc), type(exc).__name__)

    def execute(uid: Any = None) -> Any:
        with runtime_backend_only():
            return getattr(cls, operation)(**arguments)

    if operation in WRITE_OPERATIONS:
        execute = registry_write(resource, operation)(execute)
    return _run(lambda: execute(uid=arguments.get("uid")), encode_result)


def _owns_checked_delete(cls: type) -> bool:
    """Whether ``cls`` implements its own ``delete`` with its own checks.

    The table row base class's ``delete`` removes one row with no preflight, so
    a table row class deletes remotely only through its resource's service.
    Composites such as ``Curve`` or ``PricingMarketDataSetBinding`` implement
    ``delete`` themselves and run it remotely like any other operation.
    """

    from msm.api.base import MarketsMetaTableRow

    return not issubclass(cls, MarketsMetaTableRow) and "delete" in vars(cls)


def _run(call: Callable[[], Any], encode: Callable[[Any], Any]) -> RowOperationResponse | JSONResponse:
    try:
        result = call()
    except (RegistryWriteForbidden, RegistryWritePolicyError):
        raise
    except PermissionError as exc:
        return _error(403, str(exc), type(exc).__name__)
    except LookupError as exc:
        return _error(404, str(exc), type(exc).__name__)
    except NotImplementedError as exc:
        return _error(501, str(exc), type(exc).__name__)
    except (TypeError, ValueError) as exc:
        status = 409 if "Conflict" in type(exc).__name__ else 400
        return _error(status, str(exc), type(exc).__name__)
    return RowOperationResponse(result=encode(result))


def _deleted(result: Any, uid: str) -> dict[str, Any]:
    if result is None or result is False:
        raise LookupError(f"Row {uid} was not found.")
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, Mapping):
        return dict(result)
    return {"detail": "Deleted.", "uid": uid, "deleted_count": 1}


def _error(status_code: int, detail: str, error_type: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "error_type": error_type},
    )


__all__ = ["router"]
