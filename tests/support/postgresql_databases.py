"""One disposable PostgreSQL database per pytest-xdist worker.

The PostgreSQL fixtures drop and recreate the ``public`` schema of the database their URL
variable names. Workers running at the same time would drop each other's schema, so under
xdist each worker uses its own database next to the named one.
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool


def worker_database(url: URL) -> URL:
    """``url`` itself outside xdist; under xdist, ``<database>_<worker>``, created on first use.

    The worker's database is created in the same server by connecting to ``url``, so it is as
    disposable as ``url``'s and also matches ``markets_*``.
    """

    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return url
    own = url.set(database=f"{url.database}_{worker}")
    engine = sa.create_engine(
        url.set(drivername="postgresql+psycopg"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    with engine.connect() as connection:
        exists = connection.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": own.database}
        ).scalar()
        if not exists:
            connection.exec_driver_sql(f'CREATE DATABASE "{own.database}"')
    engine.dispose()
    return own
