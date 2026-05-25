from __future__ import annotations

from collections.abc import Sequence

import msm

EXAMPLE_METATABLE_NAMESPACE = "mainsequence.examples"


def configure_examples_metatable_namespace(
    namespace: str = EXAMPLE_METATABLE_NAMESPACE,
) -> None:
    """Configure example MetaTable namespace before markets models are imported."""

    from msm.bootstrap import configure_metatable_namespace

    configure_metatable_namespace(namespace)


def start_examples_runtime(
    *,
    namespace: str = EXAMPLE_METATABLE_NAMESPACE,
    labels: Sequence[str] | None = None,
):
    """Run the example MetaTable preflight and return the markets runtime."""

    return msm.start(
        namespace=namespace,
        labels=labels,
    )


__all__ = [
    "EXAMPLE_METATABLE_NAMESPACE",
    "configure_examples_metatable_namespace",
    "start_examples_runtime",
]
