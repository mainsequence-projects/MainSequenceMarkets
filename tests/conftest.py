from __future__ import annotations

import sys

import pytest

OFFLINE_RUNTIME_DATA_SOURCE_UID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def fresh_delete_rows_impacts():
    """Each test asks MetaTables for its own delete impacts (`msm.services.table_impact`
    reuses one per table for a while)."""

    def clear() -> None:
        module = sys.modules.get("msm.services.table_impact")
        if module is not None:
            module.clear_delete_rows_impact_cache()

    clear()
    yield
    clear()


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


@pytest.fixture(scope="session")
def sqlite_revisions(tmp_path_factory):
    """SQLite files migrated from an empty database to a revision, once per session.

    `sqlite_revisions.engine(path, revision)` copies the file at ``revision`` to
    ``path``; `sqlite_revisions.file("head")` is the template every `sqlite_markets`
    copies. See `tests.support.migrations.SQLiteRevisions`. Under pytest-xdist each worker
    builds its own, in its own `tmp_path_factory` directory.
    """

    from tests.support.migrations import SQLiteRevisions

    return SQLiteRevisions(tmp_path_factory.mktemp("sqlite-revisions"))


@pytest.fixture
def sqlite_markets_prepare():
    """What `sqlite_markets` runs on its copy before building the execution identity.

    Nothing, unless a module overrides this fixture with a callable that takes the
    engine, for example to create triggers or tables first.
    """

    return None


@pytest.fixture
def sqlite_markets(tmp_path, monkeypatch, sqlite_revisions, sqlite_markets_prepare):
    """A copy of a SQLite file migrated to head, served by MetaTables' own server code.

    See `tests.support.sqlite_markets.make_sqlite_markets`.
    """

    from tests.support.sqlite_markets import make_sqlite_markets

    return make_sqlite_markets(
        tmp_path,
        monkeypatch,
        template=sqlite_revisions.file("head"),
        prepare=sqlite_markets_prepare,
    )


@pytest.fixture
def postgresql_markets(monkeypatch):
    """Markets on the disposable PostgreSQL database in
    ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL``; skipped when it is not set.

    See `tests.support.postgresql_markets.postgresql_markets`.
    """

    from tests.support.postgresql_markets import postgresql_markets

    yield from postgresql_markets(monkeypatch)
