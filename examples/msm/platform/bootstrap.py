"""The examples write only to MetaTables' local SQLite runtime."""

from __future__ import annotations


def use_local_runtime() -> None:
    """Select the local runtime for this process, and refuse to write anywhere else.

    A Python process uses the hosted MetaTables API of its Environment unless it selects
    a local one, so every example that writes calls this before it imports client models.
    """

    from metatables import configure_local_client, get_runtime_status

    configure_local_client()
    state = get_runtime_status()
    if state.get("local_mode") is not True or state.get("dialect") != "sqlite":
        raise RuntimeError(
            "The examples write only to an initialized local SQLite runtime. Check it with "
            "`metatables --local runtime status`."
        )

    from msm.api.remote import active_remote_backend

    if active_remote_backend() is not None:
        raise RuntimeError(
            "The examples write only to the local runtime, and this process sends Markets "
            "row operations to the Markets API. Unset MSM_API_BACKEND, or call "
            "msm.api.remote.use_runtime_backend()."
        )


__all__ = ["use_local_runtime"]
