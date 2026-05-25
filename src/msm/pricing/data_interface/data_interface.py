import datetime
import os
from operator import attrgetter
from threading import RLock
from typing import Any, Callable, TypedDict

import pandas as pd
from cachetools import LRUCache, cachedmethod

from ..interest_rates.etl.curve_codec import (
    decompress_string_to_curve as _decompress_string_to_curve,
)


class DateInfo(TypedDict, total=False):
    """Defines the date range for a data query."""

    start_date: datetime.datetime | None
    start_date_operand: str | None
    end_date: datetime.datetime | None
    end_date_operand: str | None


UniqueIdentifierRangeMap = dict[str, DateInfo]


class MSInterface:

    # ---- bounded, shared caches (class-level) ----
    _curve_cache = LRUCache(maxsize=1024)
    _curve_cache_lock = RLock()

    _fixings_cache = LRUCache(maxsize=4096)
    _fixings_cache_lock = RLock()

    def __init__(
        self,
        instruments_configuration: Any | None = None,
        *,
        instruments_configuration_resolver: Callable[[], Any] | None = None,
    ) -> None:
        self.instruments_configuration = instruments_configuration
        self.instruments_configuration_resolver = instruments_configuration_resolver

    def set_instruments_configuration(self, instruments_configuration: Any) -> None:
        self.instruments_configuration = instruments_configuration
        self.clear_caches()

    def _get_instruments_configuration(self) -> Any:
        if self.instruments_configuration is not None:
            return self.instruments_configuration
        if self.instruments_configuration_resolver is not None:
            configuration = self.instruments_configuration_resolver()
            if configuration is not None:
                return configuration
        raise ValueError(
            "MSInterface requires an explicit instruments_configuration or "
            "instruments_configuration_resolver. Resolve InstrumentsConfiguration "
            "through MetaTable services before pricing requests."
        )

    @staticmethod
    def _configuration_data_node_uid(configuration: Any, *field_names: str) -> Any:
        for field_name in field_names:
            value = getattr(configuration, field_name, None)
            if value is None and isinstance(configuration, dict):
                value = configuration.get(field_name)
            if value is not None:
                return value
        return None

    # NOTE: caching is applied at the method boundary; body is unchanged.
    @cachedmethod(cache=attrgetter("_curve_cache"), lock=attrgetter("_curve_cache_lock"))
    def get_historical_discount_curve(self, curve_name, target_date):
        from mainsequence.logconf import logger
        from mainsequence.tdag import APIDataNode

        instrument_configuration = self._get_instruments_configuration()
        discount_curves_data_node_uid = self._configuration_data_node_uid(
            instrument_configuration,
            "discount_curves_data_node_uid",
            "discount_curves_storage_node",
        )

        if discount_curves_data_node_uid is None:
            raise Exception(
                "discount_curves_storage_node needs to be set in https://main-sequence.app Instruments Section"
            )

        data_node = APIDataNode.build_from_table_id(table_id=discount_curves_data_node_uid)

        # for test purposes only get lats observations
        use_last_observation = (
            os.environ.get("USE_LAST_OBSERVATION_MS_INSTRUMENT", "false").lower() == "true"
        )
        if use_last_observation:
            original_request_date = target_date
            update_statistics = data_node.get_update_statistics()
            target_date = update_statistics.get_last_update_for_identity(curve_name)
            logger.warning("Curve is using last observation")

        limit = target_date + datetime.timedelta(days=1)

        curve = data_node.get_ranged_data_per_asset(
            range_descriptor={
                curve_name: {
                    "start_date": target_date,
                    "start_date_operand": ">=",
                    "end_date": limit,
                    "end_date_operand": "<",
                }
            }
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

        if use_last_observation:
            target_date = original_request_date

        return nodes, target_date

    @cachedmethod(cache=attrgetter("_fixings_cache"), lock=attrgetter("_fixings_cache_lock"))
    def get_historical_fixings(
        self, reference_rate_uid: str, start_date: datetime.datetime, end_date: datetime.datetime
    ):
        """

        :param reference_rate_uid:
        :param start_date:
        :param end_date:
        :return:
        """
        import pytz  # patch

        from mainsequence.logconf import logger
        from mainsequence.tdag import APIDataNode

        instrument_configuration = self._get_instruments_configuration()
        reference_rates_fixings_data_node_uid = self._configuration_data_node_uid(
            instrument_configuration,
            "reference_rates_fixings_data_node_uid",
            "reference_rates_fixings_storage_node",
        )
        if reference_rates_fixings_data_node_uid is None:
            raise Exception(
                "reference_rates_fixings_storage_node needs to be set in https://main-sequence.app  Instruments Section"
            )

        data_node = APIDataNode.build_from_table_id(
            table_id=reference_rates_fixings_data_node_uid
        )

        fixings_df = data_node.get_ranged_data_per_asset(
            range_descriptor={
                reference_rate_uid: {
                    "start_date": start_date,
                    "start_date_operand": ">=",
                    "end_date": end_date,
                    "end_date_operand": "<=",
                }
            }
        )
        if fixings_df.empty:

            use_last_observation = (
                os.environ.get("USE_LAST_OBSERVATION_MS_INSTRUMENT", "false").lower() == "true"
            )
            if use_last_observation:
                logger.warning("Fixings are using last observation and filled forward")
                fixings_df = data_node.get_ranged_data_per_asset(
                    range_descriptor={
                        reference_rate_uid: {
                            "start_date": datetime.datetime(1900, 1, 1, tzinfo=pytz.utc),
                            "start_date_operand": ">=",
                        }
                    }
                )

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
