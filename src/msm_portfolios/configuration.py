from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
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
from msm_portfolios.asset_scope import require_asset_category_scope
from msm_portfolios.accounting.configuration import PortfolioAccountingConfiguration
from msm_portfolios.time_index import (
    REBALANCE_STRATEGY_UID_EXCLUDED_CONFIGURATION_KEYS,
    SignalWeights,
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


class PricesConfiguration(PortfolioConfigBaseModel):
    """
    Configuration for price handling and interpolation/upsampling.

    This config controls *how Portfolios fetches and shapes prices*.
    It is distinct from signal-weight validity, which is controlled by
    `SignalWeights.maximum_forward_fill()`.

    Attributes:
        upsample_frequency_id: Target frequency after interpolation (e.g., "1d", "15m").
        intraday_bar_interpolation_rule: Interpolation rule for gaps ("ffill" or "None").
        is_live: Whether the feed should be treated as live (may be ignored by some nodes).
        source_time_index_meta_table_uid:
            Registered TimeIndexMetaTable UID that stores normalized source bars.
            The source bar frequency is read from the registered table's
            time_indexed_profile.cadence.
        forward_fill_to_now: If True, extend interpolated prices up to `datetime.now(UTC)` by forward-fill.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    upsample_frequency_id: str = Field(
        default="1d",
        description=(
            "Frequency identifier for the *interpolated/upsampled* series produced by Portfolios. "
            "For daily portfolios, this is typically '1d'. For intraday portfolios, e.g. '15m'."
        ),
        examples=["1d", "15m", "30m"],
    )

    intraday_bar_interpolation_rule: str = Field(
        default="ffill",
        description=(
            "Interpolation rule used to fill gaps in intraday (minute-level) bars. "
            "Supported values in Portfolios code paths are typically 'ffill' or 'None'."
        ),
        examples=["ffill", "None"],
    )

    is_live: bool = Field(
        default=False,
        description=(
            "Marks whether this prices configuration is intended for live/streaming usage. "
            "Some helpers may ignore this flag; it is primarily descriptive/config-level metadata."
        ),
        examples=[False, True],
    )

    source_time_index_meta_table_uid: uuid.UUID | str = Field(
        ...,
        description=(
            "UID of the registered TimeIndexMetaTable that stores normalized source bars. "
            "Portfolios resolves this UID through TimeIndexTableRef.from_uid(...) "
            "so price sources are recoverable across processes without passing a live TimeIndexTableUpdater instance. "
            "The source bar frequency is read from the table's time_indexed_profile.cadence."
        ),
        examples=["00000000-0000-0000-0000-000000000000"],
    )

    forward_fill_to_now: bool = Field(
        default=False,
        description=(
            "If True, portfolio price interpolation extends the time index up to 'now' (UTC) "
            "and forward-fills the last known price. Useful for live dashboards. "
            "Does NOT make signal weights valid beyond their maximum_forward_fill."
        ),
        examples=[False, True],
    )


class AssetsConfiguration(PortfolioConfigBaseModel):
    """
    Configuration for the asset universe and price field selection.

    Attributes:
        assets_category_unique_id:
            Optional AssetCategory unique id. If provided, Portfolios will use that category
            as the universe for both prices and portfolio construction.
            If None, the signal node is expected to define its own universe via get_asset_list().
        price_type:
            Which source valuation field to use in legacy contributed price helpers.
        prices_configuration:
            Pricing configuration used to fetch and interpolate/upsample bars.
    """

    assets_category_unique_id: str | None = Field(
        default=None,
        description=(
            "AssetCategory unique identifier used as the portfolio/signal universe. "
            "msm does not resolve this identifier directly; callers should resolve "
            "the category through MetaTable services and pass asset_list."
        ),
        examples=["crypto", "etfs", None],
    )

    asset_list: list[Any] | None = Field(
        default=None,
        description=(
            "Resolved asset scope for portfolio updaters. Items may be strings, mappings, "
            "or objects with an asset_identifier field."
        ),
        json_schema_extra={"hash_excluded": True},
    )

    price_type: str = Field(
        default="close",
        min_length=1,
        description=(
            "Source valuation field used by legacy contributed price helpers. "
            "Portfolio core uses PortfolioBuildConfiguration.valuation_column."
        ),
        examples=["close", "fair_value", "nav"],
    )

    prices_configuration: PricesConfiguration = Field(
        ...,
        description=(
            "Price-source and interpolation configuration used by Portfolios when building/interpolating prices."
        ),
        examples=[
            {
                "upsample_frequency_id": "1d",
                "intraday_bar_interpolation_rule": "ffill",
                "source_time_index_meta_table_uid": "00000000-0000-0000-0000-000000000000",
                "forward_fill_to_now": False,
            }
        ],
    )

    def get_asset_list(self) -> list[Any]:
        """
        Return the explicit asset scope for this configuration.
        """
        return require_asset_category_scope(
            asset_list=self.asset_list,
            asset_category_unique_id=self.assets_category_unique_id,
            context="AssetsConfiguration",
        )


class BacktestingWeightsConfig(PortfolioConfigBaseModel):
    """
    Configuration container holding instantiated strategy objects.

    IMPORTANT (Portfolios design)
    ----------------------
    Portfolios uses **direct injection** (instances), not string lookups:
    - `signal_weights_instance` is a SignalWeights TimeIndexTableUpdater
    - `rebalance_strategy_instance` is a RebalanceStrategyBase state machine whose
      declared updater dependencies are serialized as part of its identity

    Attributes:
        rebalance_strategy_instance:
            Rebalance strategy instance controlling observed inputs, target activation,
            event selection, partial execution, and unfinished state.
        signal_weights_instance:
            Signal strategy instance producing `signal_weight` per asset and time.
            This is typically also a TDAG TimeIndexTableUpdater and is serialized using its own configuration schema.
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
        SignalWeights,
        Field(
            description=(
                "Instance of a signal weights TimeIndexTableUpdater. "
                "It is serialized from its concrete signal configuration while "
                "stored in the canonical SignalWeights table."
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
    def ser_signal_weights(self, v: SignalWeights) -> dict[str, Any]:
        """Serialize the concrete signal identity, not the canonical table identity."""
        return canonical_signal_configuration(v)

    @field_serializer(
        "rebalance_strategy_instance",
        when_used="json",
        return_type=dict[str, Any],
    )
    def ser_rebalance_strategy(self, v: RebalanceStrategyBase) -> dict[str, Any]:
        """Serialize the concrete rebalance strategy identity."""
        return canonical_rebalance_strategy_configuration(v)


class PortfolioExecutionConfiguration(PortfolioConfigBaseModel):
    """
    Configuration for execution / fee model.

    Attributes:
        commission_fee:
            Commission/fee rate applied to turnover (abs(weights_current - weights_before)).
    """

    commission_fee: float = Field(
        default=0.00018,
        ge=0.0,
        description=(
            "Commission fee rate applied as turnover drag. "
            "PortfoliosUpdater computes fees as sum(abs(w_current - w_before)) * commission_fee."
        ),
        examples=[0.00018, 0.001, 0.0],
    )


class ValuationAlignmentPolicy(PortfolioConfigBaseModel):
    """Per-asset as-of policy for consumed valuation observations (ADR 0058)."""

    model_config = ConfigDict(extra="forbid")

    maximum_staleness: dt.timedelta = Field(
        default=dt.timedelta(days=1),
        gt=dt.timedelta(0),
        description=(
            "Age past which a valuation observation is marked stale. A held asset is "
            "always valued at its last observed price, however old; a portfolio value "
            "that uses an older price has valuation_stale set. Only a held asset with no "
            "observed price at all raises. Alignment never creates timestamps."
        ),
        examples=["P1D"],
    )
    fail_on_missing_values: bool = Field(
        default=False,
        description=(
            "Raise when a held asset's last observed price is older than "
            "maximum_staleness, instead of valuing it at that price and marking the "
            "value stale (the default, ADR 0058)."
        ),
        examples=[False, True],
    )


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
    - what fee model to apply
    - how observations are aligned without manufacturing timestamps

    Attributes:
        valuation_source_instance:
            Explicit TimeIndexTableUpdater/TimeIndexTableRef valuation dependency consumed by the portfolio.
        valuation_column:
            Numeric column from the consumed valuation source used for valuation.
        valuation_asset_identifier:
            The portfolio's currency: NAV, cash and every value are in it.
        fx_source_instance:
            The portfolio's one FX source, when an asset is quoted in another currency.
        valuation_alignment_policy:
            Bounded per-asset as-of behavior for the consumed valuation frame.
        execution_configuration:
            Fee/execution model.
        backtesting_weights_configuration:
            The injected signal + rebalance strategies.
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
            "Numeric column from the consumed valuation source used for portfolio "
            "valuation and returns. Defaults to 'close' for bar-based workflows, "
            "but may be any source column such as fair_value, nav, or mark_price."
        ),
        examples=["close", "fair_value", "nav", "mark_price"],
    )

    valuation_asset_identifier: str = Field(
        ...,
        min_length=1,
        description=(
            "The portfolio's currency (ADR 0059). NAV, cash and every value are in it; the "
            "ledger, PortfolioRebalance and the weights path all read it from here."
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
                "of the base is rate units of the quote. PortfolioRebalance, the ledger "
                "and the weights path convert prices quoted in another currency into "
                "valuation_asset_identifier at the last observed rate. With it, the "
                "valuation source must have a price_asset_identifier column; without "
                "it, every asset is priced in the portfolio's currency (ADR 0059)."
            ),
        ),
        WithJsonSchema({"type": "object"}),
    ]

    valuation_alignment_policy: ValuationAlignmentPolicy = Field(
        default_factory=ValuationAlignmentPolicy,
        description=(
            "Per-asset as-of and staleness policy used at explicit execution and "
            "valuation observations."
        ),
    )

    execution_configuration: PortfolioExecutionConfiguration = Field(
        ...,
        description="Execution / fee configuration used by PortfoliosUpdater.",
        examples=[{"commission_fee": 0.00018}],
    )

    backtesting_weights_configuration: BacktestingWeightsConfig = Field(
        ...,
        description="Injected signal and rebalance strategy instances used to build the portfolio.",
    )

    accounting_configuration: PortfolioAccountingConfiguration | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Explicit opt-in position accounting configuration. Omitted and None preserve "
            "the legacy weight-return path and its serialized identity."
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
    def _fixed_cash_limit_needs_a_ledger(self) -> PortfolioBuildConfiguration:
        """A fixed-amount negative cash limit is in currency; only a ledger has one."""
        strategy = self.backtesting_weights_configuration.rebalance_strategy_instance
        if (
            self.accounting_configuration is None
            and strategy.own_execution_prices() is None
            and strategy.fill_policy().negative_cash == "fixed_amount"
        ):
            raise ValueError(
                "A fixed-amount negative cash limit needs accounting_configuration: a "
                "portfolio without a ledger has no NAV in currency, so it allows no "
                "negative cash or a fraction of NAV (ADR 0059)."
            )
        return self

    @field_serializer(
        "valuation_alignment_policy",
        when_used="json",
        return_type=dict[str, Any],
    )
    def ser_valuation_alignment_policy(
        self,
        v: ValuationAlignmentPolicy,
    ) -> dict[str, Any]:
        return v.model_dump()

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
