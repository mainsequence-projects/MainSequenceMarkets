"""Typed client for the Markets API (ADR 0047, decision 2).

``MarketsClient`` calls the deployed Markets API. Its ``backend`` runs the
``msm.api`` row class methods remotely, so an application keeps writing
``Asset.upsert(...)`` or ``Portfolio.get_by_uid(uid)`` without MetaTables
grants on ``mainsequence.markets``::

    from msm.api.remote import use_remote_backend
    from msm.client import MarketsClient

    use_remote_backend(MarketsClient.from_environment().backend)

or set ``MSM_API_BACKEND=remote``. Portfolio time series are read with
``MarketsClient.portfolio_values(...)`` and ``portfolio_weights(...)``.
"""

from __future__ import annotations

from msm.client.client import MarketsClient, RemoteRowBackend, tabular_frame_to_pandas
from msm.client.discovery import MarketsApiEndpoint, MarketsApiResolutionError

__all__ = [
    "MarketsApiEndpoint",
    "MarketsApiResolutionError",
    "MarketsClient",
    "RemoteRowBackend",
    "tabular_frame_to_pandas",
]
