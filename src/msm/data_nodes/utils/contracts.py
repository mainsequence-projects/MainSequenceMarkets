from __future__ import annotations

from dataclasses import dataclass

from mainsequence.tdag.data_nodes import RecordDefinition


MS_MARKETS_ACCOUNT_HOLDINGS_TABLE_NAME = "ms_markets__account_holdings"
MS_MARKETS_FUND_HOLDINGS_TABLE_NAME = "ms_markets__fund_holdings"
MS_MARKETS_TARGET_POSITIONS_TABLE_NAME = "ms_markets__target_positions"


@dataclass(frozen=True)
class DataNodeTableContract:
    """Backend-independent source-table contract for a markets DataNode table."""

    table_name: str
    role: str
    schema_version: int
    time_index_name: str
    unique_constraint: tuple[str, ...]
    relationship_column_name: str
    column_dtypes_map: dict[str, str]
    column_labels: dict[str, str]
    column_descriptions: dict[str, str]

    @property
    def dynamic_table_index_names(self) -> list[str]:
        return list(self.unique_constraint)

    def record_definitions(self) -> list[RecordDefinition]:
        return [
            RecordDefinition(
                column_name=column_name,
                dtype=dtype,
                label=self.column_labels.get(column_name, column_name),
                description=self.column_descriptions.get(column_name),
            )
            for column_name, dtype in self.column_dtypes_map.items()
        ]


def source_table_initialization_kwargs(
    contract: DataNodeTableContract,
) -> dict[str, object]:
    """Return generic DynamicTableMetaData/DataNode source-table init kwargs."""

    return {
        "time_index_name": contract.time_index_name,
        "index_names": contract.dynamic_table_index_names,
        "column_dtypes_map": dict(contract.column_dtypes_map),
    }


ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT = DataNodeTableContract(
    table_name=MS_MARKETS_ACCOUNT_HOLDINGS_TABLE_NAME,
    role="account_historical_holdings",
    schema_version=4,
    time_index_name="time_index",
    unique_constraint=("time_index", "account_uid", "unique_identifier"),
    relationship_column_name="holdings_set_uid",
    column_dtypes_map={
        "time_index": "datetime64[ns, UTC]",
        "account_uid": "uuid",
        "unique_identifier": "object",
        "holdings_set_uid": "uuid",
        "is_trade_snapshot": "bool",
        "quantity": "decimal",
        "target_trade_time": "datetime64[ns, UTC]",
        "extra_details": "jsonb",
    },
    column_labels={
        "time_index": "Time Index",
        "account_uid": "Account UID",
        "unique_identifier": "Unique Identifier",
        "holdings_set_uid": "Holdings Set UID",
        "is_trade_snapshot": "Is Trade Snapshot",
        "quantity": "Quantity",
        "target_trade_time": "Target Trade Time",
        "extra_details": "Extra Details",
    },
    column_descriptions={
        "time_index": (
            "UTC timestamp for the account holdings snapshot. Rows with the same "
            "account_uid and time_index belong to the same account observation."
        ),
        "account_uid": (
            "Stable Account UID that owns the holdings row. This dimension scopes "
            "holdings history to one account."
        ),
        "unique_identifier": (
            "Asset unique identifier for the held instrument at this account timestamp."
        ),
        "holdings_set_uid": "Stable UUID shared by rows written together as one account holdings set.",
        "is_trade_snapshot": "Whether the holdings row belongs to an execution or trade snapshot.",
        "quantity": "Position quantity held for this asset in the account snapshot.",
        "target_trade_time": "Requested or expected execution time for this row when provided.",
        "extra_details": "JSONB payload for provider-specific holdings attributes.",
    },
)

FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT = DataNodeTableContract(
    table_name=MS_MARKETS_FUND_HOLDINGS_TABLE_NAME,
    role="fund_historical_holdings",
    schema_version=3,
    time_index_name="time_index",
    unique_constraint=("time_index", "fund_uid", "unique_identifier"),
    relationship_column_name="holdings_set_uid",
    column_dtypes_map={
        "time_index": "datetime64[ns, UTC]",
        "fund_uid": "uuid",
        "unique_identifier": "object",
        "holdings_set_uid": "uuid",
        "is_trade_snapshot": "bool",
        "quantity": "decimal",
        "target_weight": "decimal",
        "target_trade_time": "datetime64[ns, UTC]",
        "extra_details": "jsonb",
    },
    column_labels={
        "time_index": "Time Index",
        "fund_uid": "Fund UID",
        "unique_identifier": "Unique Identifier",
        "holdings_set_uid": "Holdings Set UID",
        "is_trade_snapshot": "Is Trade Snapshot",
        "quantity": "Quantity",
        "target_weight": "Target Weight",
        "target_trade_time": "Target Trade Time",
        "extra_details": "Extra Details",
    },
    column_descriptions={
        "time_index": (
            "UTC timestamp for the fund holdings snapshot. Rows with the same "
            "fund_uid and time_index belong to the same fund observation."
        ),
        "fund_uid": (
            "Stable Fund UID that owns the holdings row. This dimension scopes "
            "holdings history to one fund."
        ),
        "unique_identifier": (
            "Asset unique identifier for the held instrument at this fund timestamp."
        ),
        "holdings_set_uid": "Stable UUID shared by rows written together as one fund holdings set.",
        "is_trade_snapshot": "Whether the holdings row belongs to an execution or trade snapshot.",
        "quantity": "Position quantity held for this asset in the fund snapshot.",
        "target_weight": "Target portfolio weight for this asset when available.",
        "target_trade_time": "Requested or expected execution time for this row when provided.",
        "extra_details": "JSONB payload for provider-specific holdings attributes.",
    },
)

POSITION_EXPOSURE_TABLE_CONTRACT = DataNodeTableContract(
    table_name=MS_MARKETS_TARGET_POSITIONS_TABLE_NAME,
    role="position_exposure",
    schema_version=1,
    time_index_name="time_index",
    unique_constraint=("time_index", "position_set_uid", "unique_identifier"),
    relationship_column_name="position_set_uid",
    column_dtypes_map={
        "time_index": "datetime64[ns, UTC]",
        "position_set_uid": "uuid",
        "unique_identifier": "object",
        "weight_notional_exposure": "decimal",
        "constant_notional_exposure": "decimal",
        "single_asset_quantity": "decimal",
    },
    column_labels={
        "time_index": "Time Index",
        "position_set_uid": "Position Set UID",
        "unique_identifier": "Unique Identifier",
        "weight_notional_exposure": "Weight Notional Exposure",
        "constant_notional_exposure": "Constant Notional Exposure",
        "single_asset_quantity": "Single Asset Quantity",
    },
    column_descriptions={
        "time_index": "Stamped time index for the reusable target position row set.",
        "position_set_uid": "Stable UUID shared by rows in one reusable target position set.",
        "unique_identifier": "Target asset or exposure unique identifier.",
        "weight_notional_exposure": "Desired exposure expressed as an account weight.",
        "constant_notional_exposure": "Desired constant notional exposure in account currency.",
        "single_asset_quantity": "Desired direct single-asset quantity exposure.",
    },
)


__all__ = [
    "ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT",
    "DataNodeTableContract",
    "FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT",
    "MS_MARKETS_ACCOUNT_HOLDINGS_TABLE_NAME",
    "MS_MARKETS_FUND_HOLDINGS_TABLE_NAME",
    "MS_MARKETS_TARGET_POSITIONS_TABLE_NAME",
    "POSITION_EXPOSURE_TABLE_CONTRACT",
    "source_table_initialization_kwargs",
]
