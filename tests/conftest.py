from __future__ import annotations

import pytest

OFFLINE_RUNTIME_DATA_SOURCE_UID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def offline_postgresql_runtime(monkeypatch):
    """Serve a hosted PostgreSQL MetaTables runtime without resolving or calling an API.

    When a repository context leaves `data_source_uid` as `None`, as product code
    does, or no `dialect=` is passed, `metatables.compiled_sql.v1` reads the
    DataSource UID and the SQL dialect together from the Environment-selected
    API runtime through `RuntimeContext.require_data_source_uid()` and
    `RuntimeContext.require_sql_dialect()`. This fixture answers
    `get_runtime_context()` offline with a runtime that satisfies both checks,
    so statement tests compile through the same automatic path.
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
    assert runtime.require_data_source_uid() == OFFLINE_RUNTIME_DATA_SOURCE_UID
    assert runtime.require_sql_dialect() == ("postgresql", "pyformat")

    def get_runtime_context() -> RuntimeContext:
        runtime.require_data_source_uid()
        return runtime

    monkeypatch.setattr(metatables.runtime_context, "get_runtime_context", get_runtime_context)
    return runtime
