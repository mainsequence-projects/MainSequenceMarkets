"""Row classes of the three published series (ADR 0060, decision 3).

``SignalWeightsSeries`` (resource ``signal-weights``), ``PortfolioWeightsSeries``
(``portfolio-weights``) and ``PortfolioValuesSeries`` (``portfolio-values``) are the
only way a signal's weights, a portfolio's executed weights and its values are written
and read. Under the ``runtime`` backend each operation is compiled SQL on Markets'
own table; under ``remote`` it is ``POST /api/v1/rows/{resource}/{operation}/``.

A key is a ``SignalMetadata.signal_uid`` for signal weights and a
``Portfolio.unique_identifier`` for the two portfolio series. ``publish`` and
``delete_after`` are registry writes: through the Markets API only the key's manager
may call them (decision 4).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Literal

from pydantic import BaseModel

from msm.api.remote import RemoteRowOperations
from msm.models import AssetTable, PortfolioTable, SignalMetadataTable
from msm_portfolios.services.series import (
    PORTFOLIO_VALUES,
    PORTFOLIO_WEIGHTS,
    SIGNAL_WEIGHTS,
    Series,
    SeriesBounds,
    SeriesDeletion,
    SeriesPublication,
    SeriesRows,
)
from msm_portfolios.time_index.portfolios.storage import PortfoliosStorage, PortfolioWeightsStorage
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage


class _SeriesOperations:
    """Operations shared by the three series; each class names its ``__series__``.

    A plain mixin: only the public class methods of the row classes themselves are
    remote operations.
    """

    __series__: ClassVar[Series]
    __required_tables__: ClassVar[list[type[Any]]]

    @classmethod
    def _context(cls):
        from msm.bootstrap import resolve_runtime

        return resolve_runtime(models=cls.__required_tables__, row_model_name=cls.__name__).context

    @classmethod
    def _publish(cls, key: str, rows: Sequence[Mapping[str, Any]]) -> SeriesPublication:
        from msm_portfolios.services.series import publish_series

        return publish_series(cls._context(), cls.__series__, key=key, rows=list(rows))

    @classmethod
    def _window(cls, **kwargs: Any) -> SeriesRows:
        from msm_portfolios.services.series import series_window

        return series_window(cls._context(), cls.__series__, **kwargs)

    @classmethod
    def _last(cls, **kwargs: Any) -> SeriesRows:
        from msm_portfolios.services.series import series_last

        return series_last(cls._context(), cls.__series__, **kwargs)

    @classmethod
    def _bounds(cls, keys: Sequence[str]) -> list[SeriesBounds]:
        from msm_portfolios.services.series import series_bounds

        return series_bounds(cls._context(), cls.__series__, keys=list(keys))

    @classmethod
    def _assets(cls, key: str) -> list[str]:
        from msm_portfolios.services.series import series_assets

        return series_assets(cls._context(), cls.__series__, key=key)

    @classmethod
    def _delete_after(cls, key: str, time: dt.datetime) -> SeriesDeletion:
        from msm_portfolios.services.series import series_delete_after

        return series_delete_after(cls._context(), cls.__series__, key=key, after=time)


class SignalWeightsSeries(_SeriesOperations, RemoteRowOperations, BaseModel):
    """A signal's weights, keyed by ``signal_uid`` and asset.

    Rows: ``time_index`` (timezone-aware), ``asset_identifier`` and ``signal_weight``.
    The rows at one time are the signal's whole set of weights then.
    """

    __resource__: ClassVar[str] = "signal-weights"
    __series__: ClassVar[Series] = SIGNAL_WEIGHTS
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        SignalMetadataTable,
        SignalWeightsStorage,
    ]

    @classmethod
    def publish(cls, key: str, rows: Sequence[Mapping[str, Any]]) -> SeriesPublication:
        """Write observations of signal ``key`` in one transaction.

        A row equal to the stored one is skipped and a different one refuses the call.
        A new observation must be after the signal's last stored time; an asset the
        signal held and the observation leaves out is written at ``0``. Times carry a
        timezone, weights are finite numbers and assets are registered. At most
        ``PUBLISH_MAX_ROWS`` rows per call. Only the signal's manager may publish.
        """

        return cls._publish(key, rows)

    @classmethod
    def window(
        cls,
        keys: Sequence[str],
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        columns: Sequence[str] | None = None,
        assets: Sequence[str] | None = None,
        limit: int = 5_000,
        offset: int = 0,
        newest_first: bool = False,
    ) -> SeriesRows:
        """Rows of ``keys`` with ``start <= time_index <= end``, by time (newest first with
        ``newest_first``), key and asset; one page of at most ``limit`` rows."""

        return cls._window(
            keys=list(keys),
            start=start,
            end=end,
            columns=None if columns is None else list(columns),
            assets=None if assets is None else list(assets),
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )

    @classmethod
    def last(
        cls,
        keys: Sequence[str],
        at: dt.datetime | None = None,
        by: Literal["key", "asset"] = "key",
        inclusive: bool = True,
        assets: Sequence[str] | None = None,
    ) -> SeriesRows:
        """The last rows at or before ``at``: per key (its last observation) or per asset."""

        return cls._last(
            keys=list(keys),
            at=at,
            by=by,
            inclusive=inclusive,
            assets=None if assets is None else list(assets),
        )

    @classmethod
    def bounds(cls, keys: Sequence[str]) -> list[SeriesBounds]:
        """First and last time and row count of each key, in the order given."""

        return cls._bounds(keys)

    @classmethod
    def assets(cls, key: str) -> list[str]:
        """Every asset the signal has ever had a row for."""

        return cls._assets(key)

    @classmethod
    def delete_after(cls, key: str, time: dt.datetime) -> SeriesDeletion:
        """Delete the signal's rows after ``time``. Only the signal's manager may call it."""

        return cls._delete_after(key, time)


class PortfolioWeightsSeries(_SeriesOperations, RemoteRowOperations, BaseModel):
    """A portfolio's executed weights, keyed by ``Portfolio.unique_identifier`` and asset.

    Rows: ``time_index``, ``asset_identifier``, ``weight``, ``weight_before``,
    ``price_current``, ``price_before``, ``volume_current``, ``volume_before``,
    ``held_shares`` and ``book_cash``; values other than the time and asset may be null.
    """

    __resource__: ClassVar[str] = "portfolio-weights"
    __series__: ClassVar[Series] = PORTFOLIO_WEIGHTS
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        PortfolioTable,
        PortfolioWeightsStorage,
    ]

    @classmethod
    def publish(cls, key: str, rows: Sequence[Mapping[str, Any]]) -> SeriesPublication:
        """Write rows of portfolio ``key`` in one transaction.

        A row equal to the stored one is skipped and a different one refuses the call;
        rows at or after the portfolio's retirement are refused. At most
        ``PUBLISH_MAX_ROWS`` rows per call. Only the portfolio's manager may publish.
        """

        return cls._publish(key, rows)

    @classmethod
    def window(
        cls,
        keys: Sequence[str],
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        columns: Sequence[str] | None = None,
        assets: Sequence[str] | None = None,
        limit: int = 5_000,
        offset: int = 0,
        newest_first: bool = False,
    ) -> SeriesRows:
        """Rows of ``keys`` with ``start <= time_index <= end``, by time (newest first with
        ``newest_first``), key and asset; one page of at most ``limit`` rows."""

        return cls._window(
            keys=list(keys),
            start=start,
            end=end,
            columns=None if columns is None else list(columns),
            assets=None if assets is None else list(assets),
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )

    @classmethod
    def last(
        cls,
        keys: Sequence[str],
        at: dt.datetime | None = None,
        by: Literal["key", "asset"] = "key",
        inclusive: bool = True,
        assets: Sequence[str] | None = None,
    ) -> SeriesRows:
        """The last rows at or before ``at``: per key (its last weights) or per asset."""

        return cls._last(
            keys=list(keys),
            at=at,
            by=by,
            inclusive=inclusive,
            assets=None if assets is None else list(assets),
        )

    @classmethod
    def bounds(cls, keys: Sequence[str]) -> list[SeriesBounds]:
        """First and last time and row count of each key, in the order given."""

        return cls._bounds(keys)

    @classmethod
    def assets(cls, key: str) -> list[str]:
        """Every asset the portfolio has ever had a weight row for."""

        return cls._assets(key)

    @classmethod
    def delete_after(cls, key: str, time: dt.datetime) -> SeriesDeletion:
        """Delete the portfolio's weight rows after ``time``; only its manager may call it."""

        return cls._delete_after(key, time)


class PortfolioValuesSeries(_SeriesOperations, RemoteRowOperations, BaseModel):
    """A portfolio's values, keyed by ``Portfolio.unique_identifier``.

    Rows: ``time_index``, ``close``, ``return``, ``calculated_close``, ``close_time``
    and ``valuation_stale``. The series has no asset column, so ``last`` answers per key
    and ``assets`` answers the assets of the portfolio's weights.
    """

    __resource__: ClassVar[str] = "portfolio-values"
    __series__: ClassVar[Series] = PORTFOLIO_VALUES
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        PortfolioTable,
        PortfoliosStorage,
        PortfolioWeightsStorage,
    ]

    @classmethod
    def publish(cls, key: str, rows: Sequence[Mapping[str, Any]]) -> SeriesPublication:
        """Write values of portfolio ``key`` in one transaction.

        A row equal to the stored one is skipped and a different one refuses the call;
        rows at or after the portfolio's retirement are refused. At most
        ``PUBLISH_MAX_ROWS`` rows per call. Only the portfolio's manager may publish.
        """

        return cls._publish(key, rows)

    @classmethod
    def window(
        cls,
        keys: Sequence[str],
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        columns: Sequence[str] | None = None,
        limit: int = 5_000,
        offset: int = 0,
        newest_first: bool = False,
    ) -> SeriesRows:
        """Rows of ``keys`` with ``start <= time_index <= end``, by time (newest first with
        ``newest_first``) and key; one page of at most ``limit`` rows."""

        return cls._window(
            keys=list(keys),
            start=start,
            end=end,
            columns=None if columns is None else list(columns),
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )

    @classmethod
    def last(
        cls,
        keys: Sequence[str],
        at: dt.datetime | None = None,
        inclusive: bool = True,
    ) -> SeriesRows:
        """Each key's last value at or before ``at``."""

        return cls._last(keys=list(keys), at=at, by="key", inclusive=inclusive)

    @classmethod
    def bounds(cls, keys: Sequence[str]) -> list[SeriesBounds]:
        """First and last time and row count of each key, in the order given."""

        return cls._bounds(keys)

    @classmethod
    def assets(cls, key: str) -> list[str]:
        """Every asset the portfolio has ever had a weight row for (its values have none)."""

        from msm_portfolios.services.series import series_assets

        return series_assets(cls._context(), PORTFOLIO_WEIGHTS, key=key)

    @classmethod
    def delete_after(cls, key: str, time: dt.datetime) -> SeriesDeletion:
        """Delete the portfolio's values after ``time``; only its manager may call it."""

        return cls._delete_after(key, time)


__all__ = [
    "PortfolioValuesSeries",
    "PortfolioWeightsSeries",
    "SeriesBounds",
    "SeriesDeletion",
    "SeriesPublication",
    "SeriesRows",
    "SignalWeightsSeries",
]
