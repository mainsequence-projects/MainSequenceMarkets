from __future__ import annotations

import pytest

OFFLINE_RUNTIME_DATA_SOURCE_UID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def offline_postgresql_runtime(monkeypatch):
    """Select a PostgreSQL MetaTables runtime without resolving or calling an API.

    `metatables.compiled_sql.v1.compile_sqlalchemy_statement` reads the SQL
    dialect, and the DataSource when the repository context selects none, from
    the API-selected runtime. Statement tests compile offline for the hosted
    PostgreSQL engine instead.
    """

    import metatables.runtime_context
    from metatables.runtime_contract import RuntimeContext

    runtime = RuntimeContext(
        git_source=None,
        dialect="postgresql",
        paramstyle="pyformat",
        data_source={"uid": OFFLINE_RUNTIME_DATA_SOURCE_UID},
        default_schema="public",
    )
    monkeypatch.setattr(metatables.runtime_context, "get_runtime_context", lambda: runtime)
    return runtime
