from __future__ import annotations

from functools import wraps
from typing import Any

from msm.settings import markets_namespace


def default_markets_hash_namespace_kwargs(cls: type, kwargs: dict[str, Any]) -> None:
    """Apply the markets hash namespace before the SDK DataNode wrapper runs."""

    if kwargs.get("test_node"):
        return

    namespace_aliases = tuple(getattr(cls, "_HASH_NAMESPACE_ALIASES", ()) or ())
    for namespace_alias in namespace_aliases:
        if namespace_alias not in kwargs:
            continue
        namespace = kwargs[namespace_alias]
        if namespace not in (None, ""):
            return
        kwargs.pop(namespace_alias)

    hash_namespace = kwargs.get("hash_namespace")
    if hash_namespace in (None, ""):
        kwargs["hash_namespace"] = markets_namespace()


def wrap_default_markets_hash_namespace(cls: type, original_init):
    """Wrap DataNode subclasses so markets namespace defaults reach SDK hashing."""

    @wraps(original_init)
    def wrapped_init(self, *args, **kwargs):
        default_markets_hash_namespace_kwargs(cls, kwargs)
        return original_init(self, *args, **kwargs)

    return wrapped_init


__all__ = [
    "default_markets_hash_namespace_kwargs",
    "wrap_default_markets_hash_namespace",
]
