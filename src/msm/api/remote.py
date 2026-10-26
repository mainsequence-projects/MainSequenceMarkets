"""The remote row backend switch (ADR 0047, decision 2).

Every ``msm.api`` row class runs its public class methods against one of two
backends:

- ``runtime`` (the default): today's compiled SQL through the Markets runtime.
  The Markets deployment and producers that own Markets tables use it.
- ``remote``: the Markets API. Every other application uses it, so it needs no
  MetaTables grant on ``mainsequence.markets``.

``Portfolio.get_by_uid(uid)`` is the same call under both. Selecting ``remote``
is process-wide (``use_remote_backend(...)`` or ``MSM_API_BACKEND=remote``) and
only affects row classes whose table lives in the Markets namespace; a
provider's own row classes keep the runtime backend, so a provider process uses
the API for Markets registries and its own runtime for its own tables.

Under ``remote`` each public class method becomes one call to
``POST /api/v1/rows/<resource>/<operation>/`` whose body holds the call's
arguments; the Markets API runs the same method on its runtime backend and
returns the result, which is decoded into the method's return type. The
operations a row class offers remotely are exactly its public class methods, so
the two backends cannot drift apart. ``apps/v1/routers/rows.py`` serves them.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import logging
import os
import re
import threading
import typing
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from typing import Any, Protocol

from pydantic import BaseModel, TypeAdapter
from pydantic_core import to_jsonable_python

logger = logging.getLogger(__name__)

MSM_API_BACKEND_ENV = "MSM_API_BACKEND"
LOCAL_ONLY_METHODS = frozenset({"start_engine", "create_schemas"})
"""Class methods that attach the local runtime; under ``remote`` they do nothing."""

WRITE_OPERATIONS = frozenset(
    {
        "create",
        "upsert",
        "update",
        "delete",
        "add",
        "bulk_delete",
        "add_portfolio",
        "remove_portfolio",
        "replace_memberships",
        "create_batch",
        "create_from_pandas_calendar",
        "reconcile_dataset_availability",
        "upsert_many",
        "add_many",
        "create_index_curve_selection",
        "upsert_index_curve_selection",
        "publish",
        "register",
        "register_signal",
        "unregister",
        "unregister_signal",
        "reconcile",
        "activate_definition",
        "retire_definition",
    }
)
"""Operations that create, update or delete registry rows; the API wraps them in
``registry_write`` so the registry write policy applies."""


class RemoteBackend(Protocol):
    """Runs one row operation on the Markets API and returns its JSON result."""

    def call(self, resource: str, operation: str, arguments: Mapping[str, Any]) -> Any: ...


class MarketsApiError(RuntimeError):
    """The Markets API refused or failed a row operation."""


class MarketsAccessError(MarketsApiError, PermissionError):
    """The caller may not run this operation (HTTP 401 or 403)."""


class MarketsConflictError(ValueError):
    """The Markets API reported a conflict (HTTP 409)."""


class MarketsOperationUnsupported(MarketsApiError, NotImplementedError):
    """The Markets API does not offer this operation remotely (HTTP 501)."""


_remote_backend: RemoteBackend | None = None
_remote_backend_lock = threading.Lock()
_runtime_only: ContextVar[bool] = ContextVar("msm_api_runtime_only", default=False)
_operations: dict[str, dict[str, Callable[..., Any]]] = {}
_classes: dict[str, type] = {}


def use_remote_backend(backend: RemoteBackend) -> None:
    """Send every Markets row operation of this process to ``backend``."""

    global _remote_backend
    with _remote_backend_lock:
        _remote_backend = backend


def use_runtime_backend() -> None:
    """Run Markets row operations against the local runtime again (the default)."""

    global _remote_backend
    with _remote_backend_lock:
        _remote_backend = None


@contextlib.contextmanager
def runtime_backend_only() -> Iterator[None]:
    """Run the enclosed row operations on the runtime backend.

    The Markets API serves remote operations inside this block so that, even in
    a process that selected ``remote``, the server side never calls itself.
    """

    token = _runtime_only.set(True)
    try:
        yield
    finally:
        _runtime_only.reset(token)


def active_remote_backend() -> RemoteBackend | None:
    """Return the process's remote backend, creating it when ``MSM_API_BACKEND=remote``."""

    global _remote_backend
    if _remote_backend is not None:
        return _remote_backend
    if os.environ.get(MSM_API_BACKEND_ENV, "").strip().lower() != "remote":
        return None
    with _remote_backend_lock:
        if _remote_backend is None:
            from msm.client import LazyRemoteBackend

            _remote_backend = LazyRemoteBackend()
            logger.info("msm.api row classes use the remote Markets API backend.")
    return _remote_backend


def remote_backend_for(cls: type) -> RemoteBackend | None:
    """Return the remote backend that serves ``cls``, or ``None`` for the runtime."""

    if _runtime_only.get():
        return None
    backend = active_remote_backend()
    if backend is None or not is_markets_owned(cls):
        return None
    return backend


def is_markets_owned(cls: type) -> bool:
    """Whether ``cls`` reads and writes a table in the Markets namespace.

    A provider's own row class (a ``MarketsMetaTableRow`` subclass over a table
    in the provider's namespace) is not, so it keeps the runtime backend.
    """

    table = getattr(cls, "__table__", None)
    sa_table = getattr(table, "__table__", None)
    if sa_table is None:
        return cls.__module__.split(".")[0] in {"msm", "msm_portfolios", "msm_pricing"}
    from msm.settings import markets_namespace

    namespace = (getattr(sa_table, "info", None) or {}).get("namespace")
    return namespace in (None, "", markets_namespace())


def resource_name(cls: type) -> str:
    """The API path segment of a row class: ``__resource__`` or its kebab-case name."""

    declared = getattr(cls, "__resource__", None)
    if declared:
        return str(declared)
    return re.sub(r"(?<!^)(?=[A-Z])", "-", cls.__name__).lower()


def remote_operations(cls: type) -> dict[str, Callable[..., Any]]:
    """The public class methods of ``cls`` that the remote backend can run."""

    operations: dict[str, Callable[..., Any]] = {}
    for klass in reversed(cls.__mro__):
        for name, value in vars(klass).items():
            if name.startswith("_") or name in LOCAL_ONLY_METHODS:
                continue
            if not isinstance(value, classmethod):
                continue
            func = value.__func__
            if getattr(func, "__msm_remote_operation__", None) is None:
                continue
            operations[name] = getattr(func, "__wrapped__", func)
    return operations


def registered_row_classes() -> dict[str, type]:
    """Every Markets row class that registered remote operations, by resource name."""

    return dict(_classes)


MARKETS_PACKAGES = frozenset({"msm", "msm_portfolios", "msm_pricing"})


def install_remote_dispatch(cls: type, *, register: bool = True) -> None:
    """Wrap every public class method of ``cls`` so it can run on the remote backend.

    Called when a row class is defined (``__pydantic_init_subclass__``); methods
    are wrapped once, where they are defined. A Markets row class defined in
    ms-markets is registered under its resource name and pins that name in
    ``__resource__``, so an application's subclass of it still reaches the same
    Markets resource.
    """

    for name, value in list(vars(cls).items()):
        if not isinstance(value, classmethod) or name.startswith("_"):
            continue
        func = value.__func__
        if getattr(func, "__msm_remote_operation__", None):
            continue
        setattr(cls, name, classmethod(_dispatching(name, func)))
    if not register or cls.__module__.split(".")[0] not in MARKETS_PACKAGES:
        return
    if not is_markets_owned(cls):
        return
    if "__resource__" not in vars(cls):
        cls.__resource__ = resource_name(cls)
    _classes[cls.__resource__] = cls


class RemoteRowOperations:
    """Mixin for Markets composites that are not table rows (for example ``CurrencySpot``).

    Their public class methods run on the remote backend like row methods do.
    """

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        install_remote_dispatch(cls)


def _dispatching(operation: str, func: Callable[..., Any]) -> Callable[..., Any]:
    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(cls, *args: Any, **kwargs: Any) -> Any:
        backend = remote_backend_for(cls)
        if backend is None:
            return func(cls, *args, **kwargs)
        if operation in LOCAL_ONLY_METHODS:
            logger.info("%s.%s does nothing under the remote backend.", cls.__name__, operation)
            return None
        bound = signature.bind(cls, *args, **kwargs)
        arguments = encode_arguments(bound)
        data = backend.call(resource_name(cls), operation, arguments)
        return decode_result(cls, operation, func, data)

    wrapper.__msm_remote_operation__ = operation  # type: ignore[attr-defined]
    return wrapper


def encode_arguments(bound: inspect.BoundArguments) -> dict[str, Any]:
    """Turn a bound call into the JSON body of a remote operation.

    Pydantic payloads keep ``exclude_unset`` semantics, so the server sees the
    same fields the runtime backend would have written.
    """

    arguments: dict[str, Any] = {}
    parameters = bound.signature.parameters
    for name, value in list(bound.arguments.items())[1:]:
        if parameters[name].kind is inspect.Parameter.VAR_KEYWORD:
            for key, item in value.items():
                arguments[key] = _encode(item)
        elif parameters[name].kind is inspect.Parameter.VAR_POSITIONAL:
            if value:
                raise TypeError("Remote row operations take no extra positional arguments.")
        else:
            arguments[name] = _encode(value)
    return arguments


def _encode(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_unset=True)
    return to_jsonable_python(value, fallback=str)


def decode_arguments(cls: type, operation: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Prepare a remote operation's JSON arguments for the runtime method.

    Values of parameters annotated with a simple type (uuid, datetime, int ...)
    are validated against that annotation; payloads stay mappings, which each
    method validates itself. ``filter`` and ``count`` keyword values, including
    ``__in`` items and ``__gte``/``__gt``/``__lte``/``__lt`` bounds, are validated
    against the row model's field of the same name.
    """

    from msm.api.base import range_lookup

    func = remote_operations(cls)[operation]
    hints = _type_hints(func)
    decoded: dict[str, Any] = {}
    fields = getattr(cls, "model_fields", {})
    for name, value in arguments.items():
        if operation in ("filter", "count") and name not in ("limit", "offset", "order_by"):
            field_name, lookup = range_lookup(name)
            if name.endswith("__in") and isinstance(value, list):
                base = name.removesuffix("__in")
                if base in fields:
                    value = [_validate_simple(fields[base].annotation, item) for item in value]
            elif lookup is not None and field_name in fields and value is not None:
                value = _validate_simple(fields[field_name].annotation, value)
            elif not name.endswith("_contains") and name in fields and value is not None:
                value = _validate_simple(fields[name].annotation, value)
            decoded[name] = value
            continue
        annotation = hints.get(name)
        decoded[name] = _validate_simple(annotation, value) if annotation is not None else value
    return decoded


def _validate_simple(annotation: Any, value: Any) -> Any:
    """Validate ``value`` against ``annotation`` when it only names plain types.

    Payload parameters (Pydantic models, mappings) are left as JSON for the
    method to validate itself, exactly as it does for a caller's mapping.
    """

    if value is None or isinstance(value, Mapping) or not _is_simple_annotation(annotation):
        return value
    try:
        return TypeAdapter(annotation).validate_python(value)
    except Exception:
        return value


_SIMPLE_TYPES = (uuid.UUID, int, float, bool, str, bytes)


def _is_simple_annotation(annotation: Any) -> bool:
    import datetime as dt
    import decimal
    import enum

    if annotation in (None, type(None), Any):
        return annotation is not Any
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return True
    if origin is not None:
        arguments = [argument for argument in typing.get_args(annotation) if argument is not Ellipsis]
        if origin in (list, tuple, set, frozenset) or str(origin) in (
            "<class 'collections.abc.Sequence'>",
            "<class 'collections.abc.Set'>",
        ):
            return all(_is_simple_annotation(argument) for argument in arguments)
        if origin in (typing.Union,) or str(origin) == "<class 'types.UnionType'>":
            return all(_is_simple_annotation(argument) for argument in arguments)
        return False
    if isinstance(annotation, type):
        return issubclass(
            annotation,
            (*_SIMPLE_TYPES, dt.date, dt.time, dt.timedelta, decimal.Decimal, enum.Enum),
        )
    return False


def encode_result(result: Any) -> Any:
    """JSON form of a row operation's result."""

    return to_jsonable_python(result, fallback=str)


def decode_result(cls: type, operation: str, func: Callable[..., Any], data: Any) -> Any:
    """Rebuild a row operation's return value from its JSON form."""

    if data is None:
        return None
    if operation in {"create", "upsert", "update", "add"} and isinstance(data, Mapping):
        return cls.model_validate(data)
    if operation in {"get_by_uid", "get_by_unique_identifier"}:
        return cls.model_validate(data)
    if operation == "get_many_by_unique_identifier":
        return {str(key): cls.model_validate(value) for key, value in dict(data).items()}
    if operation in {"filter", "filter_by_uids", "upsert_many"}:
        return [cls.model_validate(item) for item in data]
    if operation == "count":
        return int(data)
    annotation = _type_hints(func).get("return")
    if annotation is None:
        return data
    try:
        return TypeAdapter(annotation).validate_python(data)
    except Exception:
        logger.debug("Could not decode %s.%s result; returning JSON.", cls.__name__, operation)
        return data


def _type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    module = inspect.getmodule(func)
    namespace = _annotation_namespace(module) if module is not None else {}
    hints: dict[str, Any] = {}
    for name, raw in getattr(func, "__annotations__", {}).items():
        try:
            hints[name] = typing.get_type_hints(
                _Annotated(raw), globalns=namespace, localns=namespace
            )["value"]
        except Exception:
            continue
        if isinstance(hints[name], typing.TypeVar):
            hints.pop(name)
    return hints


_namespaces: dict[str, dict[str, Any]] = {}


def _annotation_namespace(module: Any) -> dict[str, Any]:
    """The module's globals plus the names it imports only under ``TYPE_CHECKING``.

    Row modules import some return types (``RelatedMetaTable`` ...) only for type
    checkers to avoid import cycles; decoding a result needs them at call time.
    """

    cached = _namespaces.get(module.__name__)
    if cached is not None:
        return cached
    import ast
    import importlib

    namespace = dict(vars(module))
    try:
        tree = ast.parse(inspect.getsource(module))
    except (OSError, TypeError, SyntaxError):
        tree = None
    for node in ast.walk(tree) if tree is not None else ():
        if not (isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test)):
            continue
        for statement in node.body:
            if not isinstance(statement, ast.ImportFrom) or not statement.module or statement.level:
                continue
            try:
                imported = importlib.import_module(statement.module)
            except ImportError:
                continue
            for alias in statement.names:
                if hasattr(imported, alias.name):
                    namespace.setdefault(alias.asname or alias.name, getattr(imported, alias.name))
    _namespaces[module.__name__] = namespace
    return namespace


class _Annotated:
    """Carry one annotation so ``typing.get_type_hints`` resolves it alone."""

    def __init__(self, annotation: Any) -> None:
        self.__annotations__ = {"value": annotation}


def raise_for_error(status_code: int, detail: str, error_type: str | None) -> None:
    """Re-raise a remote failure as the exception the runtime backend would raise."""

    if status_code in (401, 403):
        raise MarketsAccessError(detail)
    if status_code == 404:
        raise LookupError(detail)
    if status_code == 409:
        raise MarketsConflictError(detail)
    if status_code == 501:
        raise MarketsOperationUnsupported(detail)
    if status_code in (400, 422):
        if error_type == "TypeError":
            raise TypeError(detail)
        raise ValueError(detail)
    raise MarketsApiError(f"Markets API returned {status_code}: {detail}")


def new_request_id() -> str:
    return uuid.uuid4().hex


__all__ = [
    "LOCAL_ONLY_METHODS",
    "MSM_API_BACKEND_ENV",
    "MarketsAccessError",
    "MarketsApiError",
    "MarketsConflictError",
    "MarketsOperationUnsupported",
    "RemoteBackend",
    "RemoteRowOperations",
    "WRITE_OPERATIONS",
    "active_remote_backend",
    "decode_arguments",
    "decode_result",
    "encode_arguments",
    "encode_result",
    "install_remote_dispatch",
    "is_markets_owned",
    "raise_for_error",
    "registered_row_classes",
    "remote_backend_for",
    "remote_operations",
    "resource_name",
    "runtime_backend_only",
    "use_remote_backend",
    "use_runtime_backend",
]
