from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import Field

from mainsequence.client import dtype_codec as dc
from mainsequence.meta_tables import (
    DataNode,
    DataNodeConfiguration,
    PlatformTimeIndexMetaTable,
)
from msm.data_nodes.assets.asset_indexed import AssetIndexedDataNode
from msm.data_nodes.utils.storage_metadata import (
    storage_data_node_description,
    storage_data_node_identifier,
)
from msm.data_nodes.utils.namespaces import wrap_default_markets_hash_namespace
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.data_nodes.utils.storage_schema import storage_index_names, storage_time_index_name
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc
from msm.settings import markets_namespace

from .constants import (
    ASSET_IDENTIFIER,
    PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
)

StorageTable = type[PlatformTimeIndexMetaTable]


class PortfolioCanonicalDataNodeConfiguration(DataNodeConfiguration):
    """Update-scoped configuration base for canonical Portfolios DataNodes."""


class SignalWeightsConfiguration(PortfolioCanonicalDataNodeConfiguration):
    """Canonical SignalWeights table config plus runtime signal input."""

    signal_configuration: Any | None = Field(
        default=None,
        json_schema_extra={"hash_excluded": True},
    )


class PortfolioCanonicalDataNode(DataNode):
    """Base DataNode for canonical shared Portfolios tables."""

    _HASH_NAMESPACE_ALIASES = ("namespace",)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.__init__ = wrap_default_markets_hash_namespace(cls, cls.__init__)

    def __init__(
        self,
        config: PortfolioCanonicalDataNodeConfiguration | None = None,
        *args,
        namespace: str | None = None,
        **kwargs,
    ):
        """Create a canonical Portfolios node.

        ``namespace`` is the market-domain alias for DataNode ``hash_namespace``.
        The DataNode constructor wrapper consumes it before this method runs, so
        it is intentionally not forwarded as a separate config field.
        """
        resolved_config = self._validate_config(config or self.default_config())
        if args:
            raise TypeError(
                f"{self.__class__.__name__} accepts keyword-only DataNode arguments after config."
            )
        if kwargs.get("hash_namespace") in (None, ""):
            kwargs["hash_namespace"] = markets_namespace(namespace)
        storage_table = kwargs.pop("storage_table", None) or self._required_storage_table()
        super().__init__(
            config=resolved_config,
            storage_table=storage_table,
            **kwargs,
        )

    def dependencies(self) -> dict[str, DataNode]:
        return {}

    @classmethod
    def default_config(cls) -> PortfolioCanonicalDataNodeConfiguration:
        return cls._validate_config(PortfolioCanonicalDataNodeConfiguration())

    @classmethod
    def _validate_config(
        cls,
        config: PortfolioCanonicalDataNodeConfiguration,
    ) -> PortfolioCanonicalDataNodeConfiguration:
        if not isinstance(config, PortfolioCanonicalDataNodeConfiguration):
            raise TypeError(f"{cls.__name__} requires a PortfolioCanonicalDataNodeConfiguration.")
        return config

    @classmethod
    def _default_identifier(cls) -> str:
        return storage_data_node_identifier(cls._required_storage_table())

    @classmethod
    def _default_description(cls) -> str:
        return storage_data_node_description(cls._required_storage_table())

    @classmethod
    def _required_storage_table(cls) -> StorageTable:
        raise NotImplementedError(f"{cls.__name__} must define _required_storage_table().")

    @classmethod
    def _column_dtypes_map_for_storage(
        cls,
        storage_table: StorageTable | None = None,
    ) -> dict[str, str]:
        return storage_column_dtypes_map(storage_table or cls._required_storage_table())

    def _bound_column_dtypes_map(self) -> dict[str, str]:
        return storage_column_dtypes_map(self.storage_table)

    def _canonical_config(self) -> PortfolioCanonicalDataNodeConfiguration:
        return self.__class__._validate_config(
            getattr(self, "config", None) or self.default_config()
        )

    def update(self) -> pd.DataFrame:
        return _validate_canonical_frame(
            self.get_canonical_frame(),
            storage_table=self.storage_table,
            frame_name=self.__class__.__name__,
        )

    def get_canonical_frame(self) -> pd.DataFrame:
        raise ValueError(
            f"{self.__class__.__name__} requires real canonical portfolio rows. "
            "Attach a frame or override get_canonical_frame() before update()."
        )

    @classmethod
    def validate_frame(
        cls,
        data_frame: pd.DataFrame,
        *,
        storage_table: StorageTable | None = None,
    ) -> pd.DataFrame:
        return _validate_canonical_frame(
            data_frame,
            storage_table=storage_table or cls._required_storage_table(),
            frame_name=cls.__name__,
        )

    @classmethod
    def validate_weights_frame(
        cls,
        data_frame: pd.DataFrame,
        *,
        storage_table: StorageTable | None = None,
    ) -> pd.DataFrame:
        return cls.validate_frame(
            data_frame,
            storage_table=storage_table,
        )


class AssetScopedPortfolioCanonicalDataNode(PortfolioCanonicalDataNode, AssetIndexedDataNode):
    """Canonical Portfolios DataNode whose identity includes asset unique_identifier."""

    def _initialize_configuration(self, init_kwargs: dict) -> None:
        _drop_empty_framework_init_kwargs(init_kwargs)
        super()._initialize_configuration(init_kwargs=init_kwargs)


def _is_canonical_frame(
    frame: pd.DataFrame,
    *,
    storage_table: StorageTable,
) -> bool:
    return (
        isinstance(frame, pd.DataFrame)
        and isinstance(frame.index, pd.MultiIndex)
        and list(frame.index.names) == storage_index_names(storage_table)
    )


def _class_import_path(cls: type) -> dict[str, str]:
    return {
        "module": cls.__module__,
        "qualname": cls.__qualname__,
    }


def _drop_empty_framework_init_kwargs(init_kwargs: dict) -> None:
    if init_kwargs.get("hash_namespace") in (None, ""):
        init_kwargs.pop("hash_namespace", None)


def _drop_excluded_keys(value: Any, *, excluded_keys: frozenset[str]) -> Any:
    if isinstance(value, list):
        return [_drop_excluded_keys(item, excluded_keys=excluded_keys) for item in value]
    if isinstance(value, tuple):
        return tuple(_drop_excluded_keys(item, excluded_keys=excluded_keys) for item in value)
    if isinstance(value, dict):
        return {
            key: _drop_excluded_keys(item, excluded_keys=excluded_keys)
            for key, item in value.items()
            if key not in excluded_keys
        }
    return value


def _reset_frame_index(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("canonical Portfolios normalizers require a pandas DataFrame.")
    return frame.copy().reset_index()


def _empty_flat_frame(
    *,
    column_names: list[str],
) -> pd.DataFrame:
    return pd.DataFrame(columns=list(column_names))


def _require_columns(
    frame: pd.DataFrame,
    *,
    required_columns: list[str],
    frame_name: str,
) -> None:
    missing_columns = [
        column_name for column_name in required_columns if column_name not in frame.columns
    ]
    if missing_columns:
        raise ValueError(
            f"{frame_name} frame is missing required canonical columns: "
            f"{', '.join(missing_columns)}."
        )


def _normalize_pivoted_signal_weights(frame: pd.DataFrame) -> pd.DataFrame:
    if PORTFOLIO_CANONICAL_TIME_INDEX_NAME not in frame.columns:
        raise ValueError(
            "SignalWeights frame must include 'signal_weight' rows or a "
            "'time_index' column for pivoted signal weights."
        )

    value_columns = [
        column_name
        for column_name in frame.columns
        if column_name != PORTFOLIO_CANONICAL_TIME_INDEX_NAME
    ]
    if not value_columns:
        raise ValueError("Pivoted SignalWeights frame must contain asset columns to unpivot.")

    return frame.melt(
        id_vars=[PORTFOLIO_CANONICAL_TIME_INDEX_NAME],
        value_vars=value_columns,
        var_name=ASSET_IDENTIFIER,
        value_name="signal_weight",
    )


def _validate_canonical_frame(
    data_frame: pd.DataFrame,
    *,
    storage_table: StorageTable,
    frame_name: str,
) -> pd.DataFrame:
    index_names = storage_index_names(storage_table)
    time_index_name = storage_time_index_name(storage_table)
    column_dtypes_map = storage_column_dtypes_map(storage_table)
    frame = _ensure_storage_index(data_frame, index_names=index_names, frame_name=frame_name)
    flat = frame.reset_index()
    missing_columns = [
        column_name for column_name in column_dtypes_map if column_name not in flat.columns
    ]
    if missing_columns:
        raise ValueError(
            f"{frame_name} frame is missing required columns: {', '.join(missing_columns)}."
        )

    flat = _normalize_config_values(
        flat,
        time_index_name=time_index_name,
        column_dtypes_map=column_dtypes_map,
        frame_name=frame_name,
    )
    _validate_identity_values(flat, index_names=index_names, frame_name=frame_name)
    frame = flat.set_index(index_names).sort_index()
    if frame.index.has_duplicates:
        raise ValueError(
            f"{frame_name} frame contains duplicate rows for index contract {index_names}."
        )
    return frame


def _ensure_storage_index(
    data_frame: pd.DataFrame,
    *,
    index_names: list[str],
    frame_name: str,
) -> pd.DataFrame:
    frame = data_frame.copy()
    if list(frame.index.names) == index_names:
        return frame
    if all(index_name in frame.columns for index_name in index_names):
        return frame.set_index(index_names)
    raise ValueError(
        f"{frame_name} frame must use index_names "
        f"{index_names} or include those columns before validation."
    )


def _normalize_config_values(
    frame: pd.DataFrame,
    *,
    time_index_name: str,
    column_dtypes_map: dict[str, str],
    frame_name: str,
) -> pd.DataFrame:
    normalized = frame.copy()
    for column_name, dtype in column_dtypes_map.items():
        values = normalized[column_name]
        if column_name == time_index_name:
            normalized[column_name] = _normalize_time_index(values)
        elif dtype == dc.TIMESTAMP_TZ:
            normalized[column_name] = _normalize_datetime_column(values)
        elif dtype == dc.FLOAT64:
            normalized[column_name] = _normalize_float64(values, column_name=column_name)
        elif dtype == dc.STRING:
            normalized[column_name] = _normalize_string(values)
        else:
            raise ValueError(
                f"Unsupported canonical Portfolios dtype {dtype!r} for "
                f"{frame_name}.{column_name!r}."
            )
    return normalized


def _validate_identity_values(
    frame: pd.DataFrame,
    *,
    index_names: list[str],
    frame_name: str,
) -> None:
    for index_name in index_names[1:]:
        values = frame[index_name]
        invalid_values = values.isna() | (values.astype(str).str.len() == 0)
        if invalid_values.any():
            raise ValueError(f"{frame_name} frame has empty identity values for {index_name!r}.")


def _normalize_time_index(values: Any) -> pd.Series:
    return normalize_datetime64_ns_utc(values)


def _normalize_datetime_column(values: Any) -> pd.Series:
    return normalize_datetime64_ns_utc(values)


def _normalize_float64(values: Any, *, column_name: str) -> pd.Series:
    try:
        return pd.to_numeric(values, errors="raise").astype("float64")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid float64 canonical Portfolios value for {column_name!r}."
        ) from exc


def _normalize_string(values: Any) -> pd.Series:
    return values.map(lambda value: "" if pd.isna(value) else str(value)).astype("string")
