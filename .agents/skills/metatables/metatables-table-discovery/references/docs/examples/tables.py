"""Related relational and time-index table contracts for a small account ledger."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from metatables import PlatformManagedMetaTable, PlatformTimeIndexMetaTable, schema_table_name


class Base(DeclarativeBase):
    metadata = MetaData()


class Account(PlatformManagedMetaTable, Base):
    __tablename__ = schema_table_name("ledger", "account")
    __metatable_namespace__ = "ledger"
    __metatable_identifier__ = "ledger.account"
    __metatable_description__ = (
        "One row per ledger account. Accounts whose end-of-day balances the ledger "
        "observes, identified by a stable UID."
    )
    __metatable_labels__ = ["accounting", "reference-data"]

    uid: Mapped[UUID] = mapped_column(
        primary_key=True, info={"label": "Account UID", "description": "Stable Main Sequence UID of the account."}
    )
    name: Mapped[str] = mapped_column(
        String(120), info={"label": "Name", "description": "Human-readable account name shown in reports."}
    )


class Balance(PlatformTimeIndexMetaTable, Base):
    __tablename__ = schema_table_name("ledger", "balance")
    __metatable_namespace__ = "ledger"
    __metatable_identifier__ = "ledger.balance"
    __metatable_description__ = (
        "One row per account per UTC day. End-of-day account balances observed by the "
        "ledger, in each account's reporting currency."
    )
    __metatable_labels__ = ["accounting", "positions"]
    __time_index_name__ = "time_index"
    __index_names__ = ["time_index", "account_uid"]
    __cadence__ = "1d"

    time_index: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        info={"label": "Observation date", "description": "UTC day the balance applies to, at 00:00 UTC."},
    )
    account_uid: Mapped[UUID] = mapped_column(
        ForeignKey(f"{Account.__table__.fullname}.uid", ondelete="RESTRICT"), nullable=False,
        info={"label": "Account UID", "description": "Account whose balance is observed."},
    )
    balance: Mapped[float] = mapped_column(
        Float, nullable=False,
        info={"label": "Balance", "description": "End-of-day balance in the account's reporting currency."},
    )
