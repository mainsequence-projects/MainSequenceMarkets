# Local storage through the API

Local mode uses one workspace SQLite DataSource for system metadata and user rows.
Configure it in Settings and explicitly run MetaTables migrations, or select an
already initialized file. Startup never runs migrations. Local and hosted use the
same API and table workflows; a hosted deployment initializes its own runtime database.

The Python client discovers the active source through `/runtime-context/`; it does
not open a database during normal reads or writes. User-table migrations use the
common authorized provider workflow and the API-selected target.

See [local runtime](../operations/local-runtime.md) and
[initialization](../operations/catalog-migrations.md). Earlier development stores
require recreation from the current baseline; overrides cannot independently
retarget catalog and table storage.
