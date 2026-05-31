from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
from pydantic import Field

from mainsequence.client import dtype_codec as dc
from mainsequence.meta_tables import (
    DataNode,
    DataNodeConfiguration,
    PlatformTimeIndexMetaData,
)
from msm.data_nodes.assets.asset_indexed import AssetIndexedDataNode
from msm.data_nodes.utils.storage_metadata import (
    storage_data_node_description,
    storage_data_node_identifier,
)
from msm.data_nodes.utils.namespaces import wrap_default_markets_hash_namespace
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc
from msm.settings import markets_namespace

from .constants import (
    ASSET_UNIQUE_IDENTIFIER,
    PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
    SCHEMA_BOOTSTRAP_TIME_INDEX,
)

StorageTable = type[PlatformTimeIndexMetaData]


class PortfolioCanonicalDataNodeConfiguration(DataNodeConfiguration):
    """Configuration base for SDK-created canonical Portfolios data nodes."""

    index_names: list[str]

    @property
    def time_index_name(self) -> str:
        return PORTFOLIO_CANONICAL_TIME_INDEX_NAME

    @property
    def identity_index_names(self) -> list[str]:
        return self.index_names[1:]


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
        if kwargs.get("hash_namespace") in (None, ""):
            kwargs["hash_namespace"] = markets_namespace(namespace)
        super().__init__(resolved_config, *args, **kwargs)

    def dependencies(self) -> dict[str, DataNode]:
        return {}

    @classmethod
    def default_config(cls) -> PortfolioCanonicalDataNodeConfiguration:
        return cls._validate_config(
            PortfolioCanonicalDataNodeConfiguration(
                index_names=cls._required_index_names(),
            )
        )

    @classmethod
    def _validate_config(
        cls,
        config: PortfolioCanonicalDataNodeConfiguration,
    ) -> PortfolioCanonicalDataNodeConfiguration:
        if not isinstance(config, PortfolioCanonicalDataNodeConfiguration):
            raise TypeError(f"{cls.__name__} requires a PortfolioCanonicalDataNodeConfiguration.")
        if config.index_names != cls._required_index_names():
            raise ValueError(
                f"{cls.__name__} requires index_names {cls._required_index_names()!r}."
            )
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
    def _required_index_names(cls) -> list[str]:
        raise NotImplementedError

    @classmethod
    def _column_dtypes_map_for_storage(
        cls,
        storage_table: StorageTable | None = None,
    ) -> dict[str, str]:
        return storage_column_dtypes_map(storage_table or cls._required_storage_table())

    def _bound_column_dtypes_map(self) -> dict[str, str]:
        return storage_column_dtypes_map(self.storage_table)

    @classmethod
    def _schema_bootstrap_index_values(cls) -> dict[str, Any]:
        raise NotImplementedError

    def _canonical_config(self) -> PortfolioCanonicalDataNodeConfiguration:
        return self.__class__._validate_config(
            getattr(self, "config", None) or self.default_config()
        )

    def update(self) -> pd.DataFrame:
        return _validate_canonical_frame(
            self.get_canonical_frame(),
            config=self._canonical_config(),
            column_dtypes_map=self._bound_column_dtypes_map(),
            frame_name=self.__class__.__name__,
        )

    def get_canonical_frame(self) -> pd.DataFrame:
        return self.build_schema_bootstrap_frame(
            config=self._canonical_config(),
            storage_table=self.storage_table,
        )

    @classmethod
    def build_initialization_frame(cls, **kwargs) -> pd.DataFrame:
        return cls.build_schema_bootstrap_frame(**kwargs)

    @classmethod
    def build_schema_bootstrap_frame(
        cls,
        *,
        config: PortfolioCanonicalDataNodeConfiguration | None = None,
        index_values: dict[str, Any] | None = None,
        time_index: dt.datetime | pd.Timestamp = SCHEMA_BOOTSTRAP_TIME_INDEX,
        storage_table: StorageTable | None = None,
    ) -> pd.DataFrame:
        config = cls._validate_config(config or cls.default_config())
        column_dtypes_map = cls._column_dtypes_map_for_storage(storage_table)
        resolved_index_values = {
            **cls._schema_bootstrap_index_values(),
            **(index_values or {}),
        }
        row: dict[str, Any] = {
            config.time_index_name: time_index,
        }
        for index_name in config.identity_index_names:
            row[index_name] = resolved_index_values[index_name]
        for column_name, dtype in column_dtypes_map.items():
            if column_name not in row:
                row[column_name] = _schema_bootstrap_value(
                    dtype=dtype,
                    time_index=time_index,
                )
        frame = pd.DataFrame([row])
        frame = frame.set_index(config.index_names)
        return cls.validate_frame(
            frame,
            config=config,
            storage_table=storage_table,
        )

    @classmethod
    def validate_frame(
        cls,
        data_frame: pd.DataFrame,
        *,
        config: PortfolioCanonicalDataNodeConfiguration | None = None,
        storage_table: StorageTable | None = None,
    ) -> pd.DataFrame:
        return _validate_canonical_frame(
            data_frame,
            config=cls._validate_config(config or cls.default_config()),
            column_dtypes_map=cls._column_dtypes_map_for_storage(storage_table),
            frame_name=cls.__name__,
        )

    @classmethod
    def validate_weights_frame(
        cls,
        data_frame: pd.DataFrame,
        *,
        config: PortfolioCanonicalDataNodeConfiguration | None = None,
        storage_table: StorageTable | None = None,
    ) -> pd.DataFrame:
        return cls.validate_frame(
            data_frame,
            config=config,
            storage_table=storage_table,
        )

    def canonical_data_source_uid(self) -> str:
        return self.ensure_storage_ready()

    def canonical_data_source_id(self) -> str:
        return self.canonical_data_source_uid()

    def ensure_storage_ready(self, *, force_update: bool = False) -> str:
        storage = None if force_update else self._ready_storage_or_none()
        if storage is None:
            self.run(debug_mode=True, update_tree=False, force_update=True)
            storage = self._ready_storage_or_none()

        if storage is None:
            raise RuntimeError(
                f"{self.__class__.__name__} did not create a ready canonical "
                "Portfolios data node. Run the DataNode bootstrap path before writing."
            )
        return _coerce_required_uid(storage, field_name="data_node_storage")

    def _ready_storage_or_none(self):
        storage = self.data_node_storage
        if _coerce_optional_uid(storage, field_name="data_node_storage") is None:
            return None

        source_config = _storage_source_config(storage)
        if source_config is None:
            return None

        self._validate_storage_contract(source_config)
        return storage

    def _validate_storage_contract(self, source_config: Any) -> None:
        config = self._canonical_config()
        errors: list[str] = []

        time_index_name = _get_mapping_or_attr(source_config, "time_index_name")
        if time_index_name != config.time_index_name:
            errors.append(
                f"time_index_name {time_index_name!r} does not match {config.time_index_name!r}"
            )

        index_names = list(_get_mapping_or_attr(source_config, "index_names") or [])
        if index_names != config.index_names:
            errors.append(f"index_names {index_names!r} do not match {config.index_names!r}")

        column_dtypes_map = dict(_get_mapping_or_attr(source_config, "column_dtypes_map") or {})
        for column_name, expected_dtype in self._bound_column_dtypes_map().items():
            actual_dtype = column_dtypes_map.get(column_name)
            if actual_dtype != expected_dtype:
                errors.append(
                    f"{column_name!r} dtype {actual_dtype!r} does not match {expected_dtype!r}"
                )

        if errors:
            raise ValueError(
                f"{self.__class__.__name__} is bound to an incompatible "
                "canonical Portfolios data node: " + "; ".join(errors)
            )


class AssetScopedPortfolioCanonicalDataNode(PortfolioCanonicalDataNode, AssetIndexedDataNode):
    """Canonical Portfolios DataNode whose identity includes asset unique_identifier."""

    def _initialize_configuration(self, init_kwargs: dict) -> None:
        _drop_empty_framework_init_kwargs(init_kwargs)
        super()._initialize_configuration(init_kwargs=init_kwargs)


def _is_canonical_frame(
    frame: pd.DataFrame,
    *,
    config: PortfolioCanonicalDataNodeConfiguration,
) -> bool:
    return (
        isinstance(frame, pd.DataFrame)
        and isinstance(frame.index, pd.MultiIndex)
        and list(frame.index.names) == config.index_names
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
        var_name=ASSET_UNIQUE_IDENTIFIER,
        value_name="signal_weight",
    )


def _schema_bootstrap_value(
    *,
    dtype: str,
    time_index: dt.datetime | pd.Timestamp,
) -> Any:
    if dtype == dc.TIMESTAMP_TZ:
        return pd.Timestamp(time_index)
    if dtype == dc.FLOAT64:
        return 0.0
    if dtype == dc.STRING:
        return ""
    raise ValueError(f"Unsupported canonical Portfolios dtype {dtype!r}.")


def _validate_canonical_frame(
    data_frame: pd.DataFrame,
    *,
    config: PortfolioCanonicalDataNodeConfiguration,
    column_dtypes_map: dict[str, str],
    frame_name: str,
) -> pd.DataFrame:
    frame = _ensure_config_index(data_frame, config=config, frame_name=frame_name)
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
        config=config,
        column_dtypes_map=column_dtypes_map,
        frame_name=frame_name,
    )
    _validate_identity_values(flat, config=config, frame_name=frame_name)
    frame = flat.set_index(config.index_names).sort_index()
    if frame.index.has_duplicates:
        raise ValueError(
            f"{frame_name} frame contains duplicate rows for index contract {config.index_names}."
        )
    return frame


def _ensure_config_index(
    data_frame: pd.DataFrame,
    *,
    config: PortfolioCanonicalDataNodeConfiguration,
    frame_name: str,
) -> pd.DataFrame:
    expected_index_names = list(config.index_names)
    frame = data_frame.copy()
    if list(frame.index.names) == expected_index_names:
        return frame
    if all(index_name in frame.columns for index_name in expected_index_names):
        return frame.set_index(expected_index_names)
    raise ValueError(
        f"{frame_name} frame must use index_names "
        f"{expected_index_names} or include those columns before validation."
    )


def _normalize_config_values(
    frame: pd.DataFrame,
    *,
    config: PortfolioCanonicalDataNodeConfiguration,
    column_dtypes_map: dict[str, str],
    frame_name: str,
) -> pd.DataFrame:
    normalized = frame.copy()
    for column_name, dtype in column_dtypes_map.items():
        values = normalized[column_name]
        if column_name == config.time_index_name:
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
    config: PortfolioCanonicalDataNodeConfiguration,
    frame_name: str,
) -> None:
    for index_name in config.identity_index_names:
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


def _storage_source_config(storage: Any) -> Any | None:
    return (
        _get_mapping_or_attr(storage, "sourcetableconfiguration")
        or _get_mapping_or_attr(storage, "source_table_configuration")
        or _get_mapping_or_attr(storage, "source_table_config")
    )


def _get_mapping_or_attr(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)


def _coerce_required_uid(value: Any, *, field_name: str) -> str:
    value_uid = _coerce_optional_uid(value, field_name=field_name)
    if value_uid is None:
        raise ValueError(f"{field_name} must expose a public uid.")
    return value_uid


def _coerce_optional_uid(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    value_uid = value.get("uid") if isinstance(value, dict) else getattr(value, "uid", None)
    if value_uid in (None, ""):
        return None
    return str(value_uid)
