"""Register where a portfolio's datasets live (ADR 0047, decision 5).

A provider that writes a portfolio's values, weights and signal weights into its
own contract instances records them in the Markets catalog with
``PortfolioDatasets.register`` and refreshes their state with ``reconcile``.
Under the remote row backend both run on the Markets API, so the provider needs
no grant on the catalog table.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import BaseModel

from msm.api.remote import RemoteRowOperations
from msm_portfolios.services.portfolio_datasets import (
    PortfolioDatasetReconciliationResult,
    PortfolioDatasetRegistration,
    PortfolioDatasetState,
    SignalDatasetRegistration,
)


class PortfolioDatasets(RemoteRowOperations, BaseModel):
    """Register, reconcile and read a portfolio's dataset catalog row."""

    __resource__: ClassVar[str] = "portfolio-datasets"
    __required_tables__: ClassVar[list[str]] = [
        "Portfolio",
        "PortfolioDatasetAvailability",
        "SignalMetadata",
    ]

    @classmethod
    def register(
        cls,
        registration: PortfolioDatasetRegistration | Mapping[str, Any],
        *,
        reconcile: bool = True,
    ) -> PortfolioDatasetState:
        """Record the instance tables of one portfolio, verify them and reconcile.

        Each table must be visible to the Markets workload (``data_viewer``) and
        expose its contract's columns.
        """

        from msm_portfolios.services.portfolio_datasets import register_portfolio_datasets

        return register_portfolio_datasets(cls._context(), registration, reconcile=reconcile)

    @classmethod
    def register_signal(
        cls,
        registration: SignalDatasetRegistration | Mapping[str, Any],
    ) -> SignalDatasetRegistration:
        """Record the signal weights instance of one signal (``signal_uid``, ``signal_meta_table_uid``).

        ``register`` binds a portfolio's current signal; this binds any other,
        such as the earlier signals of a producer whose signal uid changes each run.
        """

        from msm_portfolios.services.portfolio_datasets import register_signal_dataset

        return register_signal_dataset(cls._context(), registration)

    @classmethod
    def reconcile(
        cls,
        *,
        portfolio_uids: Sequence[uuid.UUID | str] = (),
        portfolio_identifiers: Sequence[str] = (),
    ) -> PortfolioDatasetReconciliationResult:
        """Refresh population state, row counts and time bounds after a run."""

        from msm_portfolios.services.portfolio_datasets import (
            reconcile_portfolio_dataset_availability,
        )

        return reconcile_portfolio_dataset_availability(
            cls._context(),
            portfolio_uids=list(portfolio_uids),
            portfolio_identifiers=list(portfolio_identifiers),
        )

    @classmethod
    def get(cls, *, portfolio_uids: Sequence[uuid.UUID | str]) -> tuple[PortfolioDatasetState, ...]:
        """The catalog rows of the requested portfolios, without reconciling."""

        from msm_portfolios.services.portfolio_datasets import list_portfolio_dataset_states

        return list_portfolio_dataset_states(cls._context(), portfolio_uids=list(portfolio_uids))

    @classmethod
    def _context(cls):
        from msm.bootstrap import resolve_runtime

        return resolve_runtime(models=cls.__required_tables__, row_model_name=cls.__name__).context


__all__ = ["PortfolioDatasets"]
