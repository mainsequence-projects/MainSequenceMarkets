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
    records: list[RecordDefinition]

    @property
    def dynamic_table_index_names(self) -> list[str]:
        return list(self.unique_constraint)


def _record(
    column_name: str,
    dtype: str,
    label: str,
    description: str,
) -> RecordDefinition:
    return RecordDefinition(
        column_name=column_name,
        dtype=dtype,
        label=label,
        description=description,
    )


def source_table_initialization_kwargs(
    contract: DataNodeTableContract,
) -> dict[str, object]:
    """Return generic DynamicTableMetaData/DataNode source-table init kwargs."""

    return {
        "time_index_name": contract.time_index_name,
        "index_names": contract.dynamic_table_index_names,
        "column_dtypes_map": {record.column_name: record.dtype for record in contract.records},
    }


ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT = DataNodeTableContract(
    table_name=MS_MARKETS_ACCOUNT_HOLDINGS_TABLE_NAME,
    role="account_historical_holdings",
    schema_version=5,
    time_index_name="time_index",
    unique_constraint=("time_index", "account_uid", "unique_identifier"),
    relationship_column_name="holdings_set_uid",
    records=[
        _record(
            "time_index",
            "datetime64[ns, UTC]",
            "Time Index",
            "UTC timestamp for the account holdings snapshot. Rows with the same "
            "account_uid and time_index belong to the same account observation.",
        ),
        _record(
            "account_uid",
            "uuid",
            "Account UID",
            "Stable Account UID that owns the holdings row. This dimension scopes "
            "holdings history to one account.",
        ),
        _record(
            "unique_identifier",
            "string",
            "Unique Identifier",
            "Asset unique identifier for the held instrument at this account timestamp.",
        ),
        _record(
            "holdings_set_uid",
            "uuid",
            "Holdings Set UID",
            "Stable UUID shared by rows written together as one account holdings set.",
        ),
        _record(
            "is_trade_snapshot",
            "bool",
            "Is Trade Snapshot",
            "Whether the holdings row belongs to an execution or trade snapshot.",
        ),
        _record(
            "quantity",
            "float64",
            "Quantity",
            "Position quantity held for this asset in the account snapshot.",
        ),
        _record(
            "target_trade_time",
            "datetime64[ns, UTC]",
            "Target Trade Time",
            "Requested or expected execution time as a timezone-aware UTC datetime when provided.",
        ),
        _record(
            "extra_details",
            "jsonb",
            "Extra Details",
            "JSONB payload for provider-specific holdings attributes.",
        ),
    ],
)

FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT = DataNodeTableContract(
    table_name=MS_MARKETS_FUND_HOLDINGS_TABLE_NAME,
    role="fund_historical_holdings",
    schema_version=4,
    time_index_name="time_index",
    unique_constraint=("time_index", "fund_uid", "unique_identifier"),
    relationship_column_name="holdings_set_uid",
    records=[
        _record(
            "time_index",
            "datetime64[ns, UTC]",
            "Time Index",
            "UTC timestamp for the fund holdings snapshot. Rows with the same "
            "fund_uid and time_index belong to the same fund observation.",
        ),
        _record(
            "fund_uid",
            "uuid",
            "Fund UID",
            "Stable Fund UID that owns the holdings row. This dimension scopes "
            "holdings history to one fund.",
        ),
        _record(
            "unique_identifier",
            "string",
            "Unique Identifier",
            "Asset unique identifier for the held instrument at this fund timestamp.",
        ),
        _record(
            "holdings_set_uid",
            "uuid",
            "Holdings Set UID",
            "Stable UUID shared by rows written together as one fund holdings set.",
        ),
        _record(
            "is_trade_snapshot",
            "bool",
            "Is Trade Snapshot",
            "Whether the holdings row belongs to an execution or trade snapshot.",
        ),
        _record(
            "quantity",
            "float64",
            "Quantity",
            "Position quantity held for this asset in the fund snapshot.",
        ),
        _record(
            "target_weight",
            "float64",
            "Target Weight",
            "Target portfolio weight for this asset when available.",
        ),
        _record(
            "target_trade_time",
            "datetime64[ns, UTC]",
            "Target Trade Time",
            "Requested or expected execution time as a timezone-aware UTC datetime when provided.",
        ),
        _record(
            "extra_details",
            "jsonb",
            "Extra Details",
            "JSONB payload for provider-specific holdings attributes.",
        ),
    ],
)

POSITION_EXPOSURE_TABLE_CONTRACT = DataNodeTableContract(
    table_name=MS_MARKETS_TARGET_POSITIONS_TABLE_NAME,
    role="position_exposure",
    schema_version=2,
    time_index_name="time_index",
    unique_constraint=("time_index", "position_set_uid", "unique_identifier"),
    relationship_column_name="position_set_uid",
    records=[
        _record(
            "time_index",
            "datetime64[ns, UTC]",
            "Time Index",
            "Stamped time index for the reusable target position row set.",
        ),
        _record(
            "position_set_uid",
            "uuid",
            "Position Set UID",
            "Stable UUID shared by rows in one reusable target position set.",
        ),
        _record(
            "unique_identifier",
            "string",
            "Unique Identifier",
            "Target asset or exposure unique identifier.",
        ),
        _record(
            "weight_notional_exposure",
            "float64",
            "Weight Notional Exposure",
            "Desired exposure expressed as an account weight.",
        ),
        _record(
            "constant_notional_exposure",
            "float64",
            "Constant Notional Exposure",
            "Desired constant notional exposure in account currency.",
        ),
        _record(
            "single_asset_quantity",
            "float64",
            "Single Asset Quantity",
            "Desired direct single-asset quantity exposure.",
        ),
    ],
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
