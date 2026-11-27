"""Run the Markets migrations in tests, and share databases migrated to a revision."""

from __future__ import annotations

import datetime as dt
import shutil
import uuid
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from alembic import command

from metatables.migrations import alembic_config_for_provider
from msm.services.accounts.account_virtual_allocations import (
    virtual_fund_unique_identifier_for_target,
)
from msm_migrations import migration


def _config(connection):
    config = alembic_config_for_provider(migration, sqlalchemy_url=str(connection.engine.url))
    config.attributes["connection"] = connection
    return config


def _seed_every_table(connection, *, expected_tables: int = 62):
    metadata = sa.MetaData()
    metadata.reflect(connection)
    rows = {}
    for table in metadata.sorted_tables:
        if table.name == migration.version_table:
            continue
        row = {}
        for column in table.columns:
            if column.nullable:
                row[column.name] = None
            elif isinstance(column.type, sa.Uuid):
                row[column.name] = uuid.uuid5(uuid.NAMESPACE_URL, f"{table.name}.{column.name}")
            elif isinstance(column.type, sa.Boolean):
                row[column.name] = True
            elif isinstance(column.type, sa.DateTime):
                row[column.name] = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
            elif isinstance(column.type, sa.Date):
                row[column.name] = dt.date(2026, 1, 1)
            elif isinstance(column.type, sa.Integer):
                row[column.name] = 1
            elif isinstance(column.type, sa.Float):
                row[column.name] = 123.5
            elif isinstance(column.type, sa.Numeric):
                row[column.name] = Decimal("123.5")
            elif isinstance(column.type, sa.JSON):
                row[column.name] = {"migration": "preserve"}
            else:
                row[column.name] = f"seed-{column.name}"[:getattr(column.type, "length", None) or 255]
        for column in table.columns:
            if row[column.name] is not None and column.foreign_keys:
                target = next(iter(column.foreign_keys)).column
                row[column.name] = rows[target.table.name][target.name]
        if table.name == "ms_markets__index":
            row.update(calculation_method="custom", value_format="decimal")
        elif table.name in (
            "ms_markets__indexdatasetavailability",
            "ms_markets__portfoliodatasetavailability",
        ):
            row["population_state"] = "unavailable"
        elif table.name == "ms_markets__indexformuladefinition":
            row.update(alignment_policy="exact", missing_data_policy="fail", status="draft")
        elif table.name == "ms_markets__indexformulainput":
            row["asset_uid"] = rows["ms_markets__asset"]["uid"]
        elif table.name == "ms_markets__targetpositionsts":
            row.update(target_type="asset", target_uid=rows["ms_markets__asset"]["uid"],
                       asset_uid=rows["ms_markets__asset"]["uid"], single_asset_quantity=123.5)
        connection.execute(table.insert(), row)
        rows[table.name] = row
    fund, allocation = rows["ms_markets__virtualfund"], rows["ms_markets__accounttargetallocation"]
    # The fund's key names its account's allocation, as every fund's does (revision 0040).
    funds = metadata.tables["ms_markets__virtualfund"]
    connection.execute(
        funds.update().values(
            unique_identifier=virtual_fund_unique_identifier_for_target(
                account_uid=fund["account_uid"],
                target_portfolio_uid=fund["target_portfolio_uid"],
                account_target_allocation_uid=allocation["uid"],
            )
        )
    )
    connection.commit()
    assert len(rows) == expected_tables


class SQLiteRevisions:
    """SQLite files migrated from an empty database, one per Alembic revision.

    A file is built the first time a test asks for its revision, once per test session,
    as a test would build it: ``command.upgrade`` on a new file, then a commit. Tests get
    copies, so the shared files never change; they are read-only to make sure.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._files: dict[str, Path] = {}

    def file(self, revision: str) -> Path:
        """The shared file migrated to ``revision`` ("head" or a revision id)."""

        if revision not in self._files:
            path = self._directory / f"{revision}.sqlite"
            engine = sa.create_engine(f"sqlite:///{path}")
            with engine.connect() as connection:
                command.upgrade(_config(connection), revision)
                connection.commit()
            engine.dispose()
            path.chmod(0o444)
            self._files[revision] = path
        return self._files[revision]

    def engine(self, path: Path, revision: str) -> sa.Engine:
        """An engine on ``path``, a new copy of the file migrated to ``revision``."""

        shutil.copyfile(self.file(revision), path)
        return sa.create_engine(f"sqlite:///{path}")
