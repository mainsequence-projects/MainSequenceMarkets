from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any

import metatables.updaters.configuration as update_configuration
from msm.identity import stable_identity_payload
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    WithJsonSchema,
    field_serializer,
    model_validator,
)

from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm_portfolios.accounting.configuration import PortfolioAccountingConfiguration
from msm_portfolios.time_index import (
    REBALANCE_STRATEGY_UID_EXCLUDED_CONFIGURATION_KEYS,
    SignalWeightsSource,
    canonical_signal_configuration,
)
from msm_portfolios.time_index.base import (
    _class_import_path,
    _drop_excluded_keys,
    _isoformat_dates_and_times,
)
from msm_portfolios.rebalance_strategy import (
    RebalanceStrategyBase,
)
from msm_portfolios.utils import get_portfolios_logger

logger = get_portfolios_logger()


def canonical_valuation_source_configuration(
    valuation_source: TimeIndexTableUpdater | TimeIndexTableRef,
) -> dict[str, Any]:
    """Return the canonical hash payload for a portfolio valuation dependency."""

    if not isinstance(valuation_source, (TimeIndexTableUpdater, TimeIndexTableRef)):
        raise TypeError(
            "Portfolio valuation sources must be TimeIndexTableUpdater or TimeIndexTableRef instances."
        )

    return update_configuration.serialize_argument(valuation_source)


def canonical_rebalance_strategy_configuration(
    rebalance_strategy: Any,
) -> dict[str, Any]:
    """Return the canonical hash payload for a Portfolios rebalance strategy."""

    payload = _rebalance_strategy_payload(rebalance_strategy)
    serialized_payload = update_configuration.Serializer().serialize_init_kwargs(payload)
    canonical = _drop_excluded_keys(
        _isoformat_dates_and_times(dict(serialized_payload)),
        excluded_keys=REBALANCE_STRATEGY_UID_EXCLUDED_CONFIGURATION_KEYS,
    )
    if isinstance(rebalance_strategy, RebalanceStrategyBase):
        canonical["declared_dependencies"] = {
            name: canonical_valuation_source_configuration(dependency)
            for name, dependency in sorted(rebalance_strategy.declared_dependencies().items())
        }
    return canonical


def compute_strategy_revision(rebalance_strategy: Any) -> str:
    """Return the rebalance strategy revision recorded on portfolio ledger events."""

    payload = stable_identity_payload(
        canonical_rebalance_strategy_configuration(rebalance_strategy),
        sources=[rebalance_strategy],
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _rebalance_strategy_payload(rebalance_strategy: Any) -> dict[str, Any]:
    if isinstance(rebalance_strategy, dict):
        return rebalance_strategy

    model_dump = getattr(rebalance_strategy, "model_dump", None)
    config = model_dump() if callable(model_dump) else rebalance_strategy
    if isinstance(rebalance_strategy, RebalanceStrategyBase):
        config = dict(config)
        if rebalance_strategy.execution_model_instance is not None:
            config["execution_model_instance"] = (
                rebalance_strategy.execution_model_instance
            )
        if rebalance_strategy.execution_cost_model_instances:
            config["execution_cost_model_instances"] = (
                rebalance_strategy.execution_cost_model_instances
            )
    return {
        "rebalance_strategy_class_import_path": _class_import_path(rebalance_strategy.__class__),
        "config": config,
    }


class PortfolioConfigBaseModel(BaseModel):
    """
    Base class for Portfolios configuration models.

    Notes
    -----
    Portfolios configurations often carry non-Pydantic objects (e.g., strategy instances),
    so `arbitrary_types_allowed=True` is required.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)


class MarketsTimeSeries(PortfolioConfigBaseModel):
    """
    Reference to a MarketsTimeSeries by unique identifier.

    This is used to point price nodes to a specific upstream time series
    (e.g., "provider_1d_bars") depending on your backend setup.

    Attributes:
        unique_identifier: Identifier of the MarketsTimeSeries.
    """

    unique_identifier: str = Field(
        default="provider_1d_bars",
        description=(
            "Unique identifier of the MarketsTimeSeries to use as a price source "
            "(e.g., 'provider_1d_bars')."
        ),
        examples=["provider_1d_bars"],
    )


class BacktestingWeightsConfig(PortfolioConfigBaseModel):
    """
    Configuration container holding instantiated strategy objects.

    IMPORTANT (Portfolios design)
    ----------------------
    Portfolios uses **direct injection** (instances), not string lookups:
    - `signal_weights_instance` is the portfolio's signal: a computed `SignalWeights`
      node, which writes its own table and publishes to Markets, or a published
      signal such as `ApplicationWeights`, read from Markets (ADR 0060)
    - `rebalance_strategy_instance` is a RebalanceStrategyBase state machine whose
      declared updater dependencies are serialized as part of its identity

    Attributes:
        rebalance_strategy_instance:
            Rebalance strategy instance controlling observed inputs, target activation,
            event selection, partial execution, and unfinished state.
        signal_weights_instance:
            The signal giving `signal_weight` per asset and time. It is serialized
            from its own signal configuration, never from its table.
    """

    model_config = ConfigDict(
        extra="forbid",  # reject unknown fields
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    rebalance_strategy_instance: RebalanceStrategyBase = Field(
        ...,
        description=(
            "Dependency-declaring rebalance state machine (for example ImmediateSignal, "
            "TimeWeighted, VolumeParticipation, TrailingAverageDailyVolumeParticipation, "
            "or LiquidityConstrained). Controls how signal targets become executed "
            "portfolio weights."
        ),
        examples=[{"calendar_key": "24/7"}],
    )

    signal_weights_instance: Annotated[
        SignalWeightsSource,
        Field(
            description=(
                "The portfolio's signal: a computed SignalWeights node or a published "
                "signal (ApplicationWeights). It is serialized from its concrete signal "
                "configuration; its weights are published to Markets."
            ),
            examples=[
                # Example is intentionally schematic; actual fields depend on the strategy class.
                {"strategy": "MarketCap", "num_top_assets": 10, "source_frequency": "1d"}
            ],
        ),
        WithJsonSchema({"type": "object"}),
    ]

    @field_serializer(
        "signal_weights_instance",
        when_used="json",
        return_type=dict[str, Any],
    )
    def ser_signal_weights(self, v: SignalWeightsSource) -> dict[str, Any]:
        """Serialize the concrete signal identity."""
        return canonical_signal_configuration(v)

    @field_serializer(
        "rebalance_strategy_instance",
        when_used="json",
        return_type=dict[str, Any],
    )
    def ser_rebalance_strategy(self, v: RebalanceStrategyBase) -> dict[str, Any]:
        """Serialize the concrete rebalance strategy identity."""
        return canonical_rebalance_strategy_configuration(v)


class FrontEndDetails(PortfolioConfigBaseModel):
    """
    Optional descriptive metadata intended for UI/front-end surfaces.

    Attributes:
        description: Required human-readable description of the portfolio.
        signal_name: Optional display name for the signal strategy.
        signal_description: Optional plain-text or Markdown description of the signal strategy.
        rebalance_strategy_name: Optional display name for the rebalance strategy.
        rebalance_strategy_description: Optional description of the rebalance strategy.
    """

    description: str = Field(
        ...,
        description="Human-readable description of the portfolio shown in UI/front-end contexts.",
        examples=["Market-cap weighted crypto basket with daily rebalance."],
        min_length=1,
    )

    signal_name: str | None = Field(
        default=None,
        description="Optional display name for the signal strategy (overrides class name in UI).",
        examples=["MarketCap Top 10"],
    )

    signal_description: str | None = Field(
        default=None,
        description=(
            "Optional longer description of the signal strategy for UI. "
            "Use plain text or Markdown; HTML tags are not part of the rendering contract."
        ),
        examples=["Selects the top N assets by market cap and normalizes into weights."],
    )

    rebalance_strategy_name: str | None = Field(
        default=None,
        description="Optional display name for the rebalance strategy (overrides class name in UI).",
        examples=["Immediate Rebalance"],
    )

    rebalance_strategy_description: str | None = Field(
        default=None,
        description="Optional longer description of the rebalance strategy for UI.",
        examples=["Applies signal weights directly as executed weights on each bar."],
    )


class PortfolioMarketsConfig(PortfolioConfigBaseModel):
    """
    Portfolio metadata/config used when syncing the portfolio into the markets platform layer.

    Attributes:
        portfolio_name: Name of the portfolio in the Markets backend.
        front_end_details: Optional bundle of front-end details.
    """

    portfolio_name: str = Field(
        default="Portfolio Strategy Title",
        description="Display name for the portfolio in the markets platform.",
        examples=["Fixed Weights BTC/ETH", "Demo Portfolios Portfolio - Direct Config"],
        min_length=1,
    )

    front_end_details: FrontEndDetails | None = Field(
        default=None,
        description="Optional front-end metadata shown in UI (description + strategy details).",
        examples=[
            {
                "description": "Demo portfolio built with Portfolios",
                "signal_name": "MarketCap",
                "rebalance_strategy_name": "ImmediateSignal",
            }
        ],
    )


class PortfolioBuildConfiguration(PortfolioConfigBaseModel):
    """
    Full build configuration for a Portfolios portfolio.

    This section defines the *behavior* of the portfolio build pipeline:
    - which explicit valuation source is consumed
    - how signal weights are generated
    - which stateful rebalance strategy and observed execution dependencies are used
    - how the portfolio's ledger books and values it (ADR 0065)

    Attributes:
        valuation_source_instance:
            Explicit TimeIndexTableUpdater/TimeIndexTableRef valuation dependency consumed by the portfolio.
        valuation_column:
            Numeric column from the consumed valuation source used for valuation.
        valuation_asset_identifier:
            The portfolio's currency: NAV, cash and every value are in it.
        fx_source_instance:
            The portfolio's one FX source, when an asset is quoted in another currency.
        backtesting_weights_configuration:
            The injected signal + rebalance strategies.
        accounting_configuration:
            The portfolio's ledger: its initial NAV, valuation and lifecycle models.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    valuation_source_instance: Annotated[
        TimeIndexTableUpdater | TimeIndexTableRef,
        Field(
            description=(
                "Explicit valuation source TimeIndexTableUpdater or TimeIndexTableRef consumed by the portfolio. "
                "The source may be a market bar table, model value table, NAV table, "
                "or any asset-indexed time series with the configured valuation column. "
                "Persistent interpolation, if needed, must be prepared upstream."
            ),
            examples=[{"strategy": "InterpolatedPrices"}],
        ),
        WithJsonSchema({"type": "object"}),
    ]

    valuation_column: str = Field(
        default="close",
        min_length=1,
        description=(
            "Numeric column from the consumed valuation source: the price the rebalance "
            "sizes with and the ledger values with (ADR 0065). Defaults to 'close' for "
            "bar-based workflows, but may be any source column such as fair_value, nav, "
            "or mark_price."
        ),
        examples=["close", "fair_value", "nav", "mark_price"],
    )

    valuation_asset_identifier: str = Field(
        ...,
        min_length=1,
        description=(
            "The portfolio's currency (ADR 0059). NAV, cash and every value are in it; the "
            "ledger and PortfolioRebalance read it from here."
        ),
        examples=["USD"],
    )

    fx_source_instance: Annotated[
        TimeIndexTableUpdater | TimeIndexTableRef | None,
        Field(
            default=None,
            exclude_if=lambda value: value is None,
            description=(
                "The portfolio's one FX source, indexed by time_index, "
                "base_asset_identifier and quote_asset_identifier, with a rate: one unit "
                "of the base is rate units of the quote. PortfolioRebalance and the ledger "
                "convert prices quoted in another currency into "
                "valuation_asset_identifier at the last observed rate. With it, the "
                "valuation source must have a price_asset_identifier column; without "
                "it, every asset is priced in the portfolio's currency (ADR 0059)."
            ),
        ),
        WithJsonSchema({"type": "object"}),
    ]

    backtesting_weights_configuration: BacktestingWeightsConfig = Field(
        ...,
        description="Injected signal and rebalance strategy instances used to build the portfolio.",
    )

    accounting_configuration: PortfolioAccountingConfiguration = Field(
        ...,
        description=(
            "The portfolio's ledger (ADR 0065): every portfolio keeps one. PortfolioEngine "
            "books the fills PortfolioRebalance records and the events its lifecycle "
            "models book, and the portfolio's weights and values are projections of it."
        ),
    )

    @field_serializer(
        "valuation_source_instance",
        when_used="json",
        return_type=dict[str, Any],
    )
    def ser_valuation_source(self, v: TimeIndexTableUpdater | TimeIndexTableRef) -> dict[str, Any]:
        """Serialize the explicit valuation dependency identity, not backend update rows."""
        return canonical_valuation_source_configuration(v)

    @field_serializer("fx_source_instance", when_used="json")
    def ser_fx_source(
        self,
        v: TimeIndexTableUpdater | TimeIndexTableRef | None,
    ) -> dict[str, Any] | None:
        return None if v is None else canonical_valuation_source_configuration(v)

    @model_validator(mode="after")
    def _no_event_is_counted_twice(self) -> PortfolioBuildConfiguration:
        """Refuse a lifecycle model that books an event the prices already include.

        The valuation source states which events its prices include
        (``events_in_price``, ADR 0065); a model that books one of them would count
        it twice.
        """
        from msm_portfolios.accounting.events import events_in_price, price_includes

        in_price = events_in_price(self.valuation_source_instance)
        twice = sorted(
            {
                (model.model_identifier, event_type)
                for model in self.accounting_configuration.lifecycle_event_model_instances
                for event_type in model.booked_event_types
                if price_includes(in_price, event_type)
            }
        )
        if twice:
            listed = ", ".join(f"{event_type} ({model})" for model, event_type in twice)
            raise ValueError(
                "The valuation source's prices already include these events, and a "
                f"lifecycle model also books them, so they would be counted twice: {listed}. "
                "State on the source which events its prices include (events_in_price), "
                "or drop the model (ADR 0065)."
            )
        return self

    def model_dump(self, **kwargs):
        """
        Preserve explicit nested strategy dumping for downstream config consumers.
        """
        data = super().model_dump(**kwargs)
        data["backtesting_weights_configuration"] = (
            self.backtesting_weights_configuration.model_dump(**kwargs)
        )
        return data


class PortfolioConfiguration(PortfolioConfigBaseModel):
    """
    Top-level configuration object for a Portfolios portfolio.

    Attributes:
        portfolio_build_configuration:
            Defines the portfolio build behavior (valuation/signal/rebalance/fees).
        portfolio_markets_configuration:
            Defines the portfolio metadata used for Markets backend sync.
    """

    portfolio_build_configuration: PortfolioBuildConfiguration = Field(
        ...,
        description="Defines how the portfolio is built (valuation/signal/rebalance/fees).",
    )

    portfolio_markets_configuration: PortfolioMarketsConfig = Field(
        ...,
        description="Defines portfolio metadata used when syncing to the markets platform.",
    )
