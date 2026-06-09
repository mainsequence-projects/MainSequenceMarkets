import datetime
import os
import uuid
from operator import attrgetter
from threading import RLock
from typing import Any, Callable, TypedDict

import pandas as pd
from cachetools import LRUCache, cachedmethod

from msm.settings import INDEX_IDENTIFIER_DIMENSION
from msm_pricing.config import (
    PricingMarketDataConfiguration,
    get_pricing_market_data_configuration,
)
from msm_pricing.data_nodes.curve_codec import (
    decompress_string_to_curve as _decompress_string_to_curve,
)
from msm_pricing.data_nodes.curves import CURVE_IDENTIFIER
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
)


class DateInfo(TypedDict, total=False):
    """Defines the date range for a data query."""

    start_date: datetime.datetime | None
    start_date_operand: str | None
    end_date: datetime.datetime | None
    end_date_operand: str | None


UniqueIdentifierRangeMap = dict[str, DateInfo]


def dimension_range_for_identity(
    *,
    identity_dimension: str,
    identity: str,
    date_info: DateInfo,
) -> list[dict[str, Any]]:
    return [
        {
            "coordinate": {identity_dimension: identity},
            **date_info,
        }
    ]


class MSDataInterface:
    # ---- bounded, shared caches (class-level) ----
    _curve_cache = LRUCache(maxsize=1024)
    _curve_cache_lock = RLock()

    _fixings_cache = LRUCache(maxsize=4096)
    _fixings_cache_lock = RLock()

    def __init__(
        self,
        market_data_configuration: Any | None = None,
        *,
        market_data_configuration_resolver: Callable[[], Any] | None = None,
    ) -> None:
        self.market_data_configuration = self._coerce_market_data_configuration(
            market_data_configuration
        )
        self.market_data_configuration_resolver = market_data_configuration_resolver

    def set_market_data_configuration(self, market_data_configuration: Any) -> None:
        self.market_data_configuration = self._coerce_market_data_configuration(
            market_data_configuration
        )
        self.clear_caches()

    def _get_market_data_configuration(self) -> PricingMarketDataConfiguration:
        if self.market_data_configuration is not None:
            return self.market_data_configuration
        if self.market_data_configuration_resolver is not None:
            configuration = self.market_data_configuration_resolver()
            if configuration is not None:
                return self._coerce_market_data_configuration(configuration)
        return get_pricing_market_data_configuration()

    @staticmethod
    def _coerce_market_data_configuration(
        configuration: Any | None,
    ) -> PricingMarketDataConfiguration | None:
        if configuration is None:
            return None
        if isinstance(configuration, PricingMarketDataConfiguration):
            return configuration
        if isinstance(configuration, dict):
            return PricingMarketDataConfiguration.model_validate(configuration)
        return PricingMarketDataConfiguration.model_validate(
            {
                "market_data_set": getattr(configuration, "market_data_set"),
                "data_node_uids": getattr(
                    configuration,
                    "data_node_uids",
                    {},
                ),
            }
        )

    def _data_node_uid_for_concept(
        self,
        concept_key: str,
        *,
        market_data_set: Any | None = None,
    ) -> uuid.UUID:
        configuration = self._get_market_data_configuration()
        if market_data_set is None:
            direct_uid = configuration.direct_data_node_uid_for(concept_key)
            if direct_uid is not None:
                return direct_uid
            market_data_set = configuration.market_data_set

        return self._persisted_data_node_uid_for_concept(
            market_data_set=market_data_set,
            concept_key=concept_key,
        )

    @staticmethod
    def _persisted_data_node_uid_for_concept(
        *,
        market_data_set: Any,
        concept_key: str,
    ) -> uuid.UUID:
        from msm_pricing.api.market_data_bindings import PricingMarketDataSetBinding

        return PricingMarketDataSetBinding.resolve_data_node_uid(
            market_data_set=market_data_set,
            concept_key=concept_key,
        )

    def _data_node_for_concept(self, concept_key: str, *, market_data_set=None):
        from mainsequence.meta_tables import APIDataNode

        return APIDataNode.build_from_table_uid(
            str(
                self._data_node_uid_for_concept(
                    concept_key,
                    market_data_set=market_data_set,
                )
            )
        )

    # NOTE: caching is applied at the method boundary; body is unchanged.
    @cachedmethod(cache=attrgetter("_curve_cache"), lock=attrgetter("_curve_cache_lock"))
    def get_historical_discount_curve(self, curve_name, target_date, *, market_data_set=None):
        from mainsequence.logconf import logger

        data_node = self._data_node_for_concept(
            PRICING_CONCEPT_DISCOUNT_CURVES,
            market_data_set=market_data_set,
        )

        # for test purposes only get lats observations
        use_last_observation = (
            os.environ.get("USE_LAST_OBSERVATION_MS_INSTRUMENT", "false").lower() == "true"
        )
        if use_last_observation:
            original_request_date = target_date
            update_statistics = data_node.get_update_statistics()
            target_date = update_statistics.get_last_update_for_identity(curve_name)
            logger.warning("Curve is using last observation")

        nodes = self._read_discount_curve_nodes(
            data_node=data_node,
            curve_name=curve_name,
            target_date=target_date,
        )

        if use_last_observation:
            target_date = original_request_date

        return nodes, target_date

    def get_latest_discount_curve(self, curve_name, *, market_data_set=None):
        data_node = self._data_node_for_concept(
            PRICING_CONCEPT_DISCOUNT_CURVES,
            market_data_set=market_data_set,
        )
        update_statistics = data_node.get_update_statistics()
        target_date = update_statistics.get_last_update_for_identity(curve_name)
        if target_date is None:
            raise LookupError(f"No latest discount curve observation found for {curve_name!r}.")

        nodes = self._read_discount_curve_nodes(
            data_node=data_node,
            curve_name=curve_name,
            target_date=target_date,
        )
        return nodes, target_date

    @staticmethod
    def _read_discount_curve_nodes(*, data_node, curve_name, target_date):
        limit = target_date + datetime.timedelta(days=1)

        curve = data_node.get_df_between_dates(
            dimension_range_map=dimension_range_for_identity(
                identity_dimension=CURVE_IDENTIFIER,
                identity=curve_name,
                date_info={
                    "start_date": target_date,
                    "start_date_operand": ">=",
                    "end_date": limit,
                    "end_date_operand": "<",
                },
            )
        )

        if curve.empty:
            raise Exception(
                f"{target_date} is empty. If you want to  use the latest curve available set USE_LAST_OBSERVATION_MS_INSTRUMENT=true"
            )
        zeros = _decompress_string_to_curve(curve["curve"].iloc[0])
        zeros = pd.Series(zeros).reset_index()
        zeros["index"] = pd.to_numeric(zeros["index"])
        zeros = zeros.set_index("index")[0]

        nodes = [{"days_to_maturity": d, "zero": z} for d, z in zeros.to_dict().items() if d > 0]

        return nodes

    @cachedmethod(cache=attrgetter("_fixings_cache"), lock=attrgetter("_fixings_cache_lock"))
    def get_historical_fixings(
        self,
        reference_rate_uid: str,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        *,
        market_data_set=None,
    ):
        """

        :param reference_rate_uid:
        :param start_date:
        :param end_date:
        :return:
        """
        import pytz  # patch

        from mainsequence.logconf import logger

        data_node = self._data_node_for_concept(
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
            market_data_set=market_data_set,
        )

        fixings_df = data_node.get_df_between_dates(
            dimension_range_map=dimension_range_for_identity(
                identity_dimension=INDEX_IDENTIFIER_DIMENSION,
                identity=reference_rate_uid,
                date_info={
                    "start_date": start_date,
                    "start_date_operand": ">=",
                    "end_date": end_date,
                    "end_date_operand": "<=",
                },
            )
        )
        if fixings_df.empty:
            use_last_observation = (
                os.environ.get("USE_LAST_OBSERVATION_MS_INSTRUMENT", "false").lower() == "true"
            )
            if use_last_observation:
                logger.warning("Fixings are using last observation and filled forward")
                fixings_df = data_node.get_df_between_dates(
                    dimension_range_map=dimension_range_for_identity(
                        identity_dimension=INDEX_IDENTIFIER_DIMENSION,
                        identity=reference_rate_uid,
                        date_info={
                            "start_date": datetime.datetime(1900, 1, 1, tzinfo=pytz.utc),
                            "start_date_operand": ">=",
                        },
                    )
                )

            if fixings_df.empty:
                raise Exception(
                    f"{reference_rate_uid} has not data between {start_date} and {end_date}."
                )
        fixings_df = fixings_df.reset_index().rename(columns={"time_index": "date"})
        fixings_df["date"] = fixings_df["date"].dt.date
        return fixings_df.set_index("date")["rate"].to_dict()

    # optional helpers
    @classmethod
    def clear_caches(cls) -> None:
        cls._curve_cache.clear()
        cls._fixings_cache.clear()

    @classmethod
    def cache_info(cls) -> dict:
        return {
            "discount_curve_cache": {
                "size": cls._curve_cache.currsize,
                "max": cls._curve_cache.maxsize,
            },
            "fixings_cache": {
                "size": cls._fixings_cache.currsize,
                "max": cls._fixings_cache.maxsize,
            },
        }
