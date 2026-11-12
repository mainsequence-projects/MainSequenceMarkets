"""Register an account and write its holdings snapshot in one call (ADR 0051).

Two reads, then at most one transaction:

1. ``asset_reference_details`` for every asset the request names;
2. the account by ``unique_identifier``, with its holdings at ``holdings_date``.

From them the service decides what is missing or changed, refuses what it must before
anything is written, and sends the writes as one statement list
(``msm.repositories.account_registration``). When nothing differs it sends nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from msm.api.base import operation_result_rows
from msm.constants import ASSET_TYPE_CURRENCY_DEFINITION, BUILT_IN_ASSET_TYPE_DEFINITIONS
from msm.repositories import MarketsRepositoryContext
from msm.repositories.account_registration import (
    ACCOUNT_COLUMNS,
    AccountRegistrationWrites,
    AccountWrite,
    HoldingPosition,
    HoldingsWrite,
    SnapshotRow,
    read_account_registration_state,
    register_account as run_registration,
    with_max_rows,
)
from msm.repositories.asset_registration import NewAsset, NewAssetType
from msm.services.accounts.core import AccountHoldingsSnapshotExistsError
from msm.services.assets.currency import AssetTypeConflictError
from msm.time_index.assets.snapshots import SNAPSHOT_VALUE_COLUMNS

_BUILT_IN_ASSET_TYPES = {definition.asset_type: definition for definition in BUILT_IN_ASSET_TYPE_DEFINITIONS}


@dataclass(frozen=True)
class AccountRegistrationWrite:
    """One row, or set of rows, a registration created or changed, for the audit log."""

    resource: str
    action: str
    uid: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountRegistrationResult:
    """The registration's answer and the writes it made."""

    response: dict[str, Any]
    writes: tuple[AccountRegistrationWrite, ...] = ()


@dataclass(frozen=True)
class _RequestedAsset:
    unique_identifier: str
    asset_type: NewAssetType
    snapshot: SnapshotRow | None


@dataclass(frozen=True)
class _AccountState:
    row: dict[str, Any] | None
    holdings_set_uid: str | None
    holdings: dict[str, tuple[float | None, int, dt.datetime | None, Any]]
    holdings_complete: bool


def register_account(
    context: MarketsRepositoryContext,
    request: Any,
) -> AccountRegistrationResult:
    """Register the account in ``request`` and write its holdings snapshot (ADR 0051).

    ``request`` is an ``AccountRegistrationRequest`` or a mapping of one. Raises
    ``ValueError`` for an unknown or repeated position asset, ``AssetTypeConflictError``
    when an existing asset has another type and ``AccountHoldingsSnapshotExistsError``
    when different holdings exist at ``holdings_date`` and ``overwrite`` is false. Each
    refusal writes nothing.
    """

    from msm.api.accounts import AccountRegistrationRequest

    payload = (
        request
        if isinstance(request, AccountRegistrationRequest)
        else AccountRegistrationRequest.model_validate(request)
    )
    account_identifier = payload.account.unique_identifier.strip()
    holdings_date = _utc(payload.holdings_date)
    positions = _positions(payload.positions)
    requested = _requested_assets(payload.assets, cash_currency=payload.cash_currency)
    identifiers = tuple(
        dict.fromkeys([*requested, *(position.asset_identifier for position in positions)])
    )

    from msm.api.accounts import ACCOUNT_REGISTRATION_MAX_ASSETS

    if len(identifiers) > ACCOUNT_REGISTRATION_MAX_ASSETS:
        raise ValueError(
            f"An account registration names at most {ACCOUNT_REGISTRATION_MAX_ASSETS} assets; "
            f"this one names {len(identifiers)}."
        )

    details = _asset_details(context, identifiers)
    state = _account_state(
        context,
        account_identifier=account_identifier,
        holdings_date=holdings_date,
        position_count=len(positions),
    )

    unknown = [
        position.asset_identifier
        for position in positions
        if position.asset_identifier not in details and position.asset_identifier not in requested
    ]
    if unknown:
        names = ", ".join(repr(identifier) for identifier in unknown)
        raise ValueError(
            f"Asset {names} was not found and is not in assets."
            if len(unknown) == 1
            else f"Assets {names} were not found and are not in assets."
        )
    _refuse_asset_type_conflicts(requested, details)

    holdings = _holdings_write(
        state,
        positions=positions,
        holdings_date=holdings_date,
        overwrite=payload.overwrite,
        account_identifier=account_identifier,
    )
    missing = [asset for identifier, asset in requested.items() if identifier not in details]
    writes = AccountRegistrationWrites(
        account_identifier=account_identifier,
        holdings_date=holdings_date,
        asset_identifiers=identifiers,
        asset_types=_missing_asset_types(missing),
        assets=tuple(
            NewAsset(
                uid=uuid.uuid4(),
                unique_identifier=asset.unique_identifier,
                asset_type=asset.asset_type.asset_type,
            )
            for asset in missing
        ),
        snapshots=_changed_snapshots(requested, details, holdings_date=holdings_date),
        account=_account_write(payload.account, state.row),
        holdings=holdings,
    )
    if writes.is_empty:
        return AccountRegistrationResult(
            response=_response(
                account_row=state.row,
                asset_uids={identifier: details[identifier]["asset_uid"] for identifier in identifiers},
                holdings_set_uid=state.holdings_set_uid,
                holdings_date=holdings_date,
                written={},
            )
        )

    answer = operation_result_rows(run_registration(context, writes))
    if not answer:
        raise _snapshot_exists(account_identifier, holdings_date)
    return _result(writes, answer=answer, account_existed=state.row is not None)


def _positions(positions: Sequence[Any]) -> tuple[HoldingPosition, ...]:
    """The positions as stored: a float quantity and an int side. Each asset appears once."""

    result: list[HoldingPosition] = []
    seen: set[str] = set()
    repeated: list[str] = []
    for position in positions:
        identifier = position.asset_identifier.strip()
        if identifier in seen:
            repeated.append(identifier)
        seen.add(identifier)
        result.append(
            HoldingPosition(
                asset_identifier=identifier,
                quantity=float(Decimal(position.quantity)),
                direction=int(position.direction),
                extra_details=dict(position.extra_details),
            )
        )
    if repeated:
        raise ValueError(
            "Each position must name a different asset; repeated: "
            + ", ".join(repr(identifier) for identifier in dict.fromkeys(repeated))
            + "."
        )
    return tuple(result)


def _requested_assets(assets: Sequence[Any], *, cash_currency: str | None) -> dict[str, _RequestedAsset]:
    """The assets the request may create, by identifier, the cash currency included."""

    requested: dict[str, _RequestedAsset] = {}
    for asset in assets:
        identifier = asset.unique_identifier.strip()
        if identifier in requested:
            raise ValueError(f"Asset {identifier!r} is listed twice in assets.")
        requested[identifier] = _RequestedAsset(
            unique_identifier=identifier,
            asset_type=_asset_type_definition(asset.asset_type),
            snapshot=_snapshot_row(identifier, asset.snapshot),
        )
    if cash_currency is None:
        return requested

    code = cash_currency.strip()
    if not code:
        raise ValueError("cash_currency cannot be empty.")
    listed = requested.get(code)
    currency_type = ASSET_TYPE_CURRENCY_DEFINITION.asset_type
    if listed is not None and listed.asset_type.asset_type != currency_type:
        raise ValueError(
            f"cash_currency {code!r} is listed in assets with asset_type "
            f"{listed.asset_type.asset_type!r}, not {currency_type!r}."
        )
    if listed is None:
        requested[code] = _RequestedAsset(
            unique_identifier=code,
            asset_type=NewAssetType.from_definition(ASSET_TYPE_CURRENCY_DEFINITION),
            snapshot=None,
        )
    return requested


def _asset_type_definition(asset_type: Any) -> NewAssetType:
    """The asset type to create: the built-in definition for a built-in key."""

    built_in = _BUILT_IN_ASSET_TYPES.get(asset_type.asset_type)
    if built_in is not None:
        return NewAssetType.from_definition(built_in)
    return NewAssetType(
        uid=uuid.uuid4(),
        asset_type=asset_type.asset_type,
        display_name=asset_type.display_name,
        description=asset_type.description,
    )


def _snapshot_row(identifier: str, snapshot: Any) -> SnapshotRow | None:
    if snapshot is None:
        return None
    row = SnapshotRow(
        asset_identifier=identifier,
        **{name: getattr(snapshot, name) for name in SNAPSHOT_VALUE_COLUMNS},
    )
    if not any(_snapshot_value(getattr(row, name)) for name in SNAPSHOT_VALUE_COLUMNS):
        return None
    return row


def _asset_details(
    context: MarketsRepositoryContext,
    identifiers: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Read 1: each existing asset's uid, type and latest snapshot, in one select."""

    from msm.services.assets import asset_reference_details

    rows = asset_reference_details(
        list(identifiers),
        repository_context=with_max_rows(context, len(identifiers)),
    )
    return {
        str(row["asset_identifier"]): dict(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("asset_identifier") not in (None, "")
    }


def _account_state(
    context: MarketsRepositoryContext,
    *,
    account_identifier: str,
    holdings_date: dt.datetime,
    position_count: int,
) -> _AccountState:
    """Read 2: the account and its holdings at ``holdings_date``, in one select.

    One more row than the request's positions is read: more stored rows than positions
    already means the holdings differ.
    """

    result = read_account_registration_state(
        context,
        account_identifier=account_identifier,
        holdings_date=holdings_date,
        max_rows=position_count + 1,
    )
    rows = operation_result_rows(result)
    if not rows:
        return _AccountState(row=None, holdings_set_uid=None, holdings={}, holdings_complete=True)
    holdings = {
        str(row["holding_asset_identifier"]): (
            None if row.get("holding_quantity") is None else float(row["holding_quantity"]),
            int(row["holding_direction"]),
            _datetime_or_none(row.get("holding_target_trade_time")),
            _json_value(row.get("holding_extra_details")) or {},
        )
        for row in rows
        if row.get("holding_asset_identifier") not in (None, "")
    }
    return _AccountState(
        row=_account_row(rows[0]),
        holdings_set_uid=_string_or_none(rows[0].get("holdings_set_uid")),
        holdings=holdings,
        holdings_complete=len(holdings) <= position_count,
    )


def _refuse_asset_type_conflicts(
    requested: Mapping[str, _RequestedAsset],
    details: Mapping[str, Mapping[str, Any]],
) -> None:
    """An existing asset keeps its type; a different requested type refuses the call."""

    from msm.api.assets import normalize_asset_type

    conflicts = []
    for identifier, asset in requested.items():
        existing = details.get(identifier)
        if existing is None:
            continue
        stored = normalize_asset_type(existing.get("asset_type"))
        wanted = asset.asset_type.asset_type
        if stored != wanted:
            conflicts.append(f"{identifier!r} is {stored!r}, not {wanted!r}")
    if conflicts:
        raise AssetTypeConflictError(
            "Existing assets keep their asset_type; change it through the asset routes or "
            "send the stored type: " + "; ".join(conflicts) + "."
        )


def _holdings_write(
    state: _AccountState,
    *,
    positions: Sequence[HoldingPosition],
    holdings_date: dt.datetime,
    overwrite: bool,
    account_identifier: str,
) -> HoldingsWrite | None:
    """The holdings to write, or ``None`` when the stored ones equal the request."""

    if state.holdings_set_uid is not None:
        if _same_holdings(state, positions=positions, holdings_date=holdings_date):
            return None
        if not overwrite:
            raise _snapshot_exists(account_identifier, holdings_date)
    return HoldingsWrite(
        holdings_set_uid=uuid.uuid4(),
        positions=tuple(positions),
        overwrite=overwrite,
    )


def _same_holdings(
    state: _AccountState,
    *,
    positions: Sequence[HoldingPosition],
    holdings_date: dt.datetime,
) -> bool:
    if not state.holdings_complete or len(state.holdings) != len(positions):
        return False
    for position in positions:
        stored = state.holdings.get(position.asset_identifier)
        wanted = (position.quantity, position.direction, holdings_date, dict(position.extra_details))
        if stored != wanted:
            return False
    return True


def _missing_asset_types(missing: Sequence[_RequestedAsset]) -> tuple[NewAssetType, ...]:
    """The asset types of the assets to create, once each; the first description wins."""

    asset_types: dict[str, NewAssetType] = {}
    for asset in missing:
        asset_types.setdefault(asset.asset_type.asset_type, asset.asset_type)
    return tuple(asset_types.values())


def _changed_snapshots(
    requested: Mapping[str, _RequestedAsset],
    details: Mapping[str, Mapping[str, Any]],
    *,
    holdings_date: dt.datetime,
) -> tuple[SnapshotRow, ...]:
    """Snapshot rows to write at ``holdings_date`` (ADR 0051, decision 6).

    An asset gets one when it has no snapshot, or when its latest snapshot is earlier than
    ``holdings_date`` and differs in a value column. A latest snapshot at or after
    ``holdings_date`` is never written over or before.
    """

    rows: list[SnapshotRow] = []
    for identifier, asset in requested.items():
        if asset.snapshot is None:
            continue
        existing = details.get(identifier)
        latest_time = None if existing is None else _datetime_or_none(existing.get("snapshot_time"))
        if latest_time is None:
            rows.append(asset.snapshot)
            continue
        if latest_time >= holdings_date:
            continue
        if any(
            _snapshot_value(getattr(asset.snapshot, name)) != _snapshot_value(existing.get(name))
            for name in SNAPSHOT_VALUE_COLUMNS
        ):
            rows.append(asset.snapshot)
    return tuple(rows)


def _snapshot_value(value: Any) -> str:
    """A snapshot value as compared: a missing value equals an empty string."""

    return "" if value is None else str(value)


def _account_write(account: Any, row: Mapping[str, Any] | None) -> AccountWrite | None:
    """The account fields to write: all of them when it is missing, else only on a change."""

    write = AccountWrite(
        uid=uuid.uuid4(),
        account_name=account.account_name,
        is_paper=account.is_paper,
        account_is_active=account.account_is_active,
    )
    if row is None:
        return write
    if row.get("account_name") != account.account_name:
        return write
    for flag in ("is_paper", "account_is_active"):
        wanted = getattr(account, flag)
        if wanted is not None and bool(row.get(flag)) != wanted:
            return write
    return None


def _result(
    writes: AccountRegistrationWrites,
    *,
    answer: Sequence[Mapping[str, Any]],
    account_existed: bool,
) -> AccountRegistrationResult:
    """The answer from the transaction's last statement, and the audit records."""

    first = answer[0]
    account_row = _account_row(first)
    account_uid = str(account_row["uid"])
    holdings_set_uid = _string_or_none(first.get("holdings_set_uid"))
    identifier = writes.account_identifier
    audit: list[AccountRegistrationWrite] = []
    written = {}

    chosen_types = {item.uid: item for item in writes.asset_types}
    created_types = {
        _uuid(row["asset_type_uid"])
        for row in answer
        if row.get("asset_type_uid") is not None and _uuid(row["asset_type_uid"]) in chosen_types
    }
    for type_uid in sorted(created_types, key=lambda uid: chosen_types[uid].asset_type):
        audit.append(
            AccountRegistrationWrite(
                "asset-type",
                "create",
                str(type_uid),
                {"asset_type": chosen_types[type_uid].asset_type, "account_identifier": identifier},
            )
        )
    written["asset_types"] = {"created": len(created_types)}

    chosen_assets = {item.uid: item for item in writes.assets}
    created_assets = [row for row in answer if _uuid(row["asset_uid"]) in chosen_assets]
    for row in created_assets:
        audit.append(
            AccountRegistrationWrite(
                "asset",
                "create",
                str(_uuid(row["asset_uid"])),
                {
                    "unique_identifier": str(row["asset_identifier"]),
                    "asset_type": row.get("asset_type"),
                    "account_identifier": identifier,
                },
            )
        )
    written["assets"] = {"created": len(created_assets)}

    if writes.snapshots:
        audit.append(
            AccountRegistrationWrite(
                "asset-snapshot",
                "create",
                None,
                {
                    "asset_identifiers": [row.asset_identifier for row in writes.snapshots],
                    "time_index": writes.holdings_date.isoformat(),
                    "account_identifier": identifier,
                },
            )
        )
    written["asset_snapshots"] = {"created": len(writes.snapshots)}

    account_created = writes.account is not None and _uuid(account_uid) == writes.account.uid
    account_changed = writes.account is not None and not account_created
    if writes.account is not None:
        audit.append(
            AccountRegistrationWrite(
                "account",
                "create" if account_created else "update",
                account_uid,
                {"account_identifier": identifier},
            )
        )
    written["accounts"] = {"created": int(account_created), "changed": int(account_changed)}

    holdings_created = (
        writes.holdings is not None
        and holdings_set_uid is not None
        and _uuid(holdings_set_uid) == writes.holdings.holdings_set_uid
    )
    holdings_replaced = writes.holdings is not None and not holdings_created
    row_count = int(first.get("holdings_row_count") or 0) if writes.holdings is not None else 0
    if writes.holdings is not None:
        audit.append(
            AccountRegistrationWrite(
                "account-holdings",
                "add" if holdings_created else "replace",
                holdings_set_uid,
                {
                    "row_count": row_count,
                    "holdings_date": writes.holdings_date.isoformat(),
                    "account_uid": account_uid,
                    "account_identifier": identifier,
                },
            )
        )
    written["holdings_sets"] = {"created": int(holdings_created), "changed": int(holdings_replaced)}
    written["holdings"] = {"created": row_count}

    return AccountRegistrationResult(
        response=_response(
            account_row=account_row,
            asset_uids={str(row["asset_identifier"]): row["asset_uid"] for row in answer},
            holdings_set_uid=holdings_set_uid,
            holdings_date=writes.holdings_date,
            written=written,
        ),
        writes=tuple(audit),
    )


def _response(
    *,
    account_row: Mapping[str, Any] | None,
    asset_uids: Mapping[str, Any],
    holdings_set_uid: str | None,
    holdings_date: dt.datetime,
    written: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    from msm.api.accounts import ACCOUNT_REGISTRATION_TABLES

    if account_row is None or holdings_set_uid is None:
        raise RuntimeError("Account registration did not find its account or holdings set.")
    return {
        "account": dict(account_row),
        "asset_uids": {identifier: str(_uuid(uid)) for identifier, uid in asset_uids.items()},
        "holdings_set_uid": str(_uuid(holdings_set_uid)),
        "holdings_date": holdings_date,
        "written": {
            table: {"created": 0, "changed": 0, **dict(written.get(table, {}))}
            for table in ACCOUNT_REGISTRATION_TABLES
        },
    }


def _snapshot_exists(account_identifier: str, holdings_date: dt.datetime) -> AccountHoldingsSnapshotExistsError:
    return AccountHoldingsSnapshotExistsError(
        "A different account holdings snapshot already exists for account "
        f"{account_identifier!r} at {holdings_date.isoformat()}; send overwrite=true to "
        "replace it."
    )


def _account_row(row: Mapping[str, Any]) -> dict[str, Any]:
    account = {name: row.get(name) for name in ACCOUNT_COLUMNS}
    account["metadata_json"] = _json_value(account.get("metadata_json"))
    return account


def _json_value(value: Any) -> Any:
    """A JSON column's value; SQLite answers JSON as text."""

    if isinstance(value, str):
        return json.loads(value)
    return value


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _datetime_or_none(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return _utc(value)
    raw = str(value)
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    return _utc(dt.datetime.fromisoformat(raw))


def _uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _string_or_none(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


__all__ = [
    "AccountRegistrationResult",
    "AccountRegistrationWrite",
    "register_account",
]
