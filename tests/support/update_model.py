"""Helpers shared by the ``update_model`` tests of core and of ``msm_portfolios``."""

from __future__ import annotations

import uuid

from msm.models import markets_sqlalchemy_models
from msm.repositories.base import MarketsRepositoryContext

ROW_UID = uuid.UUID("8b7c3f0e-2d41-4a6e-9f15-3c2b1a0d9e87")


def _context() -> MarketsRepositoryContext:
    return MarketsRepositoryContext(limits={"max_rows": 100, "statement_timeout_ms": 5000})


def _set_clause(operation) -> str:
    sql = operation.statement.sql
    return sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]


def bind_test_meta_table_uids(monkeypatch) -> None:
    for model in markets_sqlalchemy_models():
        monkeypatch.setattr(model, "__metatable_uid__", str(uuid.uuid4()), raising=False)
