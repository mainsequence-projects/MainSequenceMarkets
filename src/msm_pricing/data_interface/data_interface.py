import datetime
import uuid
from collections.abc import Mapping
from operator import attrgetter
from threading import RLock
from typing import Any, Callable, TypedDict

import pandas as pd
from cachetools import LRUCache, cachedmethod
from sqlalchemy import func, select

from msm.settings import INDEX_IDENTIFIER_DIMENSION
from msm_pricing.config import (
    PricingMarketDataConfiguration,
    get_pricing_market_data_configuration,
)
from msm_pricing.data_nodes.curve_codec import (
    decompress_string_to_curve as _decompress_string_to_curve,
)
from msm_pricing.data_nodes.curves import CURVE_IDENTIFIER
from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
from msm_pricing.data_nodes.curves.key_nodes import (
    decompress_key_nodes_from_string as _decompress_key_nodes_from_string,
    normalize_curve_key_nodes as _normalize_curve_key_nodes,
)
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


class DiscountCurveNode(TypedDict):
    days_to_maturity: int | float
    zero: float


class DiscountCurveObservation(TypedDict):
    curve_identifier: str
    time_index: datetime.datetime | None
    nodes: list[DiscountCurveNode]
    key_nodes: Any | None
    metadata_json: dict[str, Any] | None


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

    _curve_observation_cache = LRUCache(maxsize=1024)
    _curve_observation_cache_lock = RLock()

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
        observation, effective_date = self.get_historical_discount_curve_observation(
            curve_name,
            target_date,
            market_data_set=market_data_set,
        )
        return observation["nodes"], effective_date

    @cachedmethod(
        cache=attrgetter("_curve_observation_cache"),
        lock=attrgetter("_curve_observation_cache_lock"),
    )
    def get_historical_discount_curve_observation(
        self,
        curve_name,
        target_date,
        *,
        market_data_set=None,
    ):
        data_node = self._data_node_for_concept(
            PRICING_CONCEPT_DISCOUNT_CURVES,
            market_data_set=market_data_set,
        )

        observation = self._read_discount_curve_observation(
            data_node=data_node,
            curve_name=curve_name,
            target_date=target_date,
        )

        return observation, target_date

    def get_historical_discount_curve_observations(
        self,
        curve_names: list[str] | tuple[str, ...] | set[str],
        target_date,
        *,
        market_data_set=None,
    ) -> dict[str, tuple[DiscountCurveObservation, datetime.datetime]]:
        """Return latest-at-or-before discount curve observations for many curves."""

        requested_curve_names = list(dict.fromkeys(str(name) for name in curve_names))
        if not requested_curve_names:
            return {}

        target_dt = _ensure_datetime(target_date)
        data_node = self._data_node_for_concept(
            PRICING_CONCEPT_DISCOUNT_CURVES,
            market_data_set=market_data_set,
        )
        rows = self._read_latest_discount_curve_observation_rows(
            data_node=data_node,
            curve_names=requested_curve_names,
            target_dt=target_dt,
        )
        observations: dict[str, tuple[DiscountCurveObservation, datetime.datetime]] = {}
        rows_by_curve = {str(row[CURVE_IDENTIFIER]): row for row in rows}
        for curve_name, row in rows_by_curve.items():
            effective_date = _ensure_datetime(row["time_index"])
            observations[curve_name] = (
                self._discount_curve_observation_from_row(row=row, curve_name=curve_name),
                effective_date,
            )
        return observations

    @staticmethod
    def _read_latest_discount_curve_observation_rows(
        *,
        data_node,
        curve_names: list[str],
        target_dt: datetime.datetime,
    ) -> list[dict[str, Any]]:
        from msm.api.base import operation_result_rows
        from msm.repositories.base import (
            MarketsRepositoryContext,
            compile_markets_statement,
            execute_markets_operation,
        )

        storage_table = getattr(data_node, "storage_table", None)
        if storage_table is None:
            raise RuntimeError(
                "Discount curve latest-as-of query requires APIDataNode.storage_table. "
                "Resolve curve storage with APIDataNode.build_from_table_uid(...)."
            )

        DiscountCurvesStorage._bind_meta_table(storage_table)
        ranked = (
            select(
                DiscountCurvesStorage.time_index.label("time_index"),
                DiscountCurvesStorage.curve_identifier.label(CURVE_IDENTIFIER),
                DiscountCurvesStorage.curve.label("curve"),
                DiscountCurvesStorage.key_nodes.label("key_nodes"),
                DiscountCurvesStorage.metadata_json.label("metadata_json"),
                func.row_number()
                .over(
                    partition_by=DiscountCurvesStorage.curve_identifier,
                    order_by=DiscountCurvesStorage.time_index.desc(),
                )
                .label("observation_rank"),
            )
            .where(
                DiscountCurvesStorage.curve_identifier.in_(curve_names),
                DiscountCurvesStorage.time_index <= target_dt,
            )
            .subquery("ranked_discount_curve_observations")
        )
        statement = select(
            ranked.c.time_index,
            ranked.c.curve_identifier,
            ranked.c.curve,
            ranked.c.key_nodes,
            ranked.c.metadata_json,
        ).where(ranked.c.observation_rank == 1)

        context = MarketsRepositoryContext(limits={"max_rows": len(curve_names)})
        operation = compile_markets_statement(
            statement,
            context=context,
            operation="select",
            models=[DiscountCurvesStorage],
            access="read",
        )
        return operation_result_rows(execute_markets_operation(operation, context=context))

    def get_latest_discount_curve(self, curve_name, *, market_data_set=None):
        observation, target_date = self.get_latest_discount_curve_observation(
            curve_name,
            market_data_set=market_data_set,
        )
        return observation["nodes"], target_date

    def get_latest_discount_curve_observation(self, curve_name, *, market_data_set=None):
        data_node = self._data_node_for_concept(
            PRICING_CONCEPT_DISCOUNT_CURVES,
            market_data_set=market_data_set,
        )
        update_statistics = data_node.get_update_statistics()
        target_date = update_statistics.get_last_update_for_identity(curve_name)
        if target_date is None:
            raise LookupError(f"No latest discount curve observation found for {curve_name!r}.")

        observation = self._read_discount_curve_observation(
            data_node=data_node,
            curve_name=curve_name,
            target_date=target_date,
        )
        return observation, target_date

    @staticmethod
    def _read_discount_curve_nodes(*, data_node, curve_name, target_date):
        return MSDataInterface._read_discount_curve_observation(
            data_node=data_node,
            curve_name=curve_name,
            target_date=target_date,
        )["nodes"]

    @staticmethod
    def _read_discount_curve_observation(*, data_node, curve_name, target_date):
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
            raise Exception(f"{target_date} is empty for curve {curve_name!r}.")

        row = curve.reset_index().iloc[0].to_dict()
        return MSDataInterface._discount_curve_observation_from_row(
            row=row,
            curve_name=curve_name,
        )

    @staticmethod
    def _discount_curve_observation_from_row(*, row: Mapping[str, Any], curve_name: str):
        compressed_curve = row.get("curve")
        if not isinstance(compressed_curve, str) or not compressed_curve:
            raise ValueError(
                f"Discount curve observation for {curve_name!r} at "
                f"{row.get('time_index')!r} has no compressed curve payload."
            )

        zeros = _decompress_string_to_curve(compressed_curve)
        zeros = pd.Series(zeros).reset_index()
        zeros["index"] = pd.to_numeric(zeros["index"])
        zeros = zeros.set_index("index")[0]

        nodes = [{"days_to_maturity": d, "zero": z} for d, z in zeros.to_dict().items() if d > 0]

        return {
            "curve_identifier": str(row.get(CURVE_IDENTIFIER) or curve_name),
            "time_index": _optional_datetime(row.get("time_index")),
            "nodes": nodes,
            "key_nodes": _optional_json_container(row.get("key_nodes")),
            "metadata_json": _optional_mapping(row.get("metadata_json")),
        }

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
            raise Exception(
                f"{reference_rate_uid} has not data between {start_date} and {end_date}."
            )
        fixings_df = fixings_df.reset_index().rename(columns={"time_index": "date"})
        fixings_df["date"] = pd.to_datetime(fixings_df["date"], utc=True).dt.date
        return fixings_df.set_index("date")["rate"].to_dict()

    def get_index_fixing_observations(
        self,
        reference_rate_uid: str,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        *,
        market_data_set=None,
    ) -> dict[datetime.date, float]:
        """Return stored fixing observations without fallback or missing-data errors."""

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
            return {}

        fixings_df = fixings_df.reset_index().rename(columns={"time_index": "date"})
        fixings_df["date"] = pd.to_datetime(fixings_df["date"], utc=True).dt.date
        return fixings_df.set_index("date")["rate"].to_dict()

    def get_historical_fixings_for_identifiers(
        self,
        reference_rate_uids: list[str] | tuple[str, ...] | set[str],
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        *,
        market_data_set=None,
    ) -> dict[str, dict[datetime.date, float]]:
        """Return historical fixings for many reference-rate identifiers in one read."""

        requested_identifiers = list(dict.fromkeys(str(uid) for uid in reference_rate_uids))
        if not requested_identifiers:
            return {}

        data_node = self._data_node_for_concept(
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
            market_data_set=market_data_set,
        )
        fixings_df = data_node.get_df_between_dates(
            dimension_range_map=[
                dimension_range_for_identity(
                    identity_dimension=INDEX_IDENTIFIER_DIMENSION,
                    identity=reference_rate_uid,
                    date_info={
                        "start_date": start_date,
                        "start_date_operand": ">=",
                        "end_date": end_date,
                        "end_date_operand": "<=",
                    },
                )[0]
                for reference_rate_uid in requested_identifiers
            ]
        )
        if fixings_df.empty:
            return {reference_rate_uid: {} for reference_rate_uid in requested_identifiers}

        fixings_df = fixings_df.reset_index().rename(columns={"time_index": "date"})
        fixings_df["date"] = pd.to_datetime(fixings_df["date"], utc=True).dt.date
        result: dict[str, dict[datetime.date, float]] = {
            reference_rate_uid: {} for reference_rate_uid in requested_identifiers
        }
        for reference_rate_uid, rows in fixings_df.groupby(INDEX_IDENTIFIER_DIMENSION):
            result[str(reference_rate_uid)] = rows.set_index("date")["rate"].astype(float).to_dict()
        return result

    # optional helpers
    @classmethod
    def clear_caches(cls) -> None:
        cls._curve_cache.clear()
        cls._curve_observation_cache.clear()
        cls._fixings_cache.clear()

    @classmethod
    def cache_info(cls) -> dict:
        return {
            "discount_curve_cache": {
                "size": cls._curve_cache.currsize,
                "max": cls._curve_cache.maxsize,
            },
            "discount_curve_observation_cache": {
                "size": cls._curve_observation_cache.currsize,
                "max": cls._curve_observation_cache.maxsize,
            },
            "fixings_cache": {
                "size": cls._fixings_cache.currsize,
                "max": cls._fixings_cache.maxsize,
            },
        }


def _optional_datetime(value: Any) -> datetime.datetime | None:
    if _is_missing_optional(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        return pd.Timestamp(value).to_pydatetime()
    return None


def _optional_json_container(value: Any) -> Any | None:
    if _is_missing_optional(value):
        return None
    if isinstance(value, str):
        return _decompress_key_nodes_from_string(value)
    if isinstance(value, Mapping):
        return _normalize_curve_key_nodes(value)
    if isinstance(value, list):
        return _normalize_curve_key_nodes(value)
    raise ValueError(
        "Discount curve observation key_nodes must be compressed JSON, a JSON object, "
        "or a JSON list when present."
    )


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    if _is_missing_optional(value):
        return None
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("Discount curve observation metadata_json must be a mapping when present.")


def _is_missing_optional(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return bool(pd.isna(value))
    return False


def _ensure_datetime(
    value: datetime.date | datetime.datetime | pd.Timestamp | str,
) -> datetime.datetime:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        return pd.Timestamp(value).to_pydatetime()
    return datetime.datetime.combine(value, datetime.time())
