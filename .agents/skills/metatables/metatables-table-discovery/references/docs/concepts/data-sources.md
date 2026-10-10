# DataSources

A DataSource is a database registration in the connected MetaTables catalog.
It has a stable UID, engine, display name, connection configuration and storage
access mode. It is independent of namespaces: tables in different namespaces can
use the same source. Physical table identity is source UID, schema and table name.

The API owns source registration and chooses its table-workflow default. The
Python client and Admin site use the same management API for PostgreSQL, MySQL,
and Microsoft SQL Server (MSSQL). TimescaleDB is a PostgreSQL engine variant.
Local bootstrap explicitly initializes one SQLite runtime source for the Git workspace.
It requires no platform Secret or registered branch. Remote source management is
available only in hosted mode; local mode rejects registration and mutation of
DataSources and cannot select a remote default or explicit remote UID.

## Supported engines and operations

| Database | API `class_type` | Registration, configuration, validation, removal | Table reads/writes, registration and migrations | Default port / schema |
| --- | --- | --- | --- | --- |
| PostgreSQL | `postgresql` | Supported | Supported | `5432` / `public` |
| TimescaleDB | `timescale_db` | Supported | Supported; extension operations require installed TimescaleDB | `5432` / `public` |
| MySQL | `mysql` | Supported | Supported | `3306` / database name |
| Microsoft SQL Server | `mssql` | Supported | Supported | `1433` / `dbo` |
| SQLite | `sqlite` | Local runtime registration; read-only metadata in the management API | Supported within the [local SQL limits](../operations/local-runtime.md) | Bound workspace file / `public` |

Every hosted engine can be the runtime DataSource. A hosted deployment declares it
in the API's `configuration.yaml`, and the deployment's migration Job initializes the
system schema and registers that same connection ([hosted runtime](../operations/hosted-runtime.md)).
A connection probe proves connectivity; migration and schema verification are separate
steps. Only the runtime source can execute table operations; other registrations are
not additional execution databases. DuckDB remains unsupported.

See the [DataSource API guide](../api/data-sources.md) for configuration fields,
engine-specific examples, error behavior and API-server driver installation.

The [runtime binding](architecture.md) holds one DataSource containing MetaTables'
system catalog and default application tables. In Local mode, Settings configures and
inspects the SQLite file before catalog tables exist, then explicitly runs system
Alembic and registers the source; an existing compatible file can be selected without
migration. Hosted Settings is read-only.

Registrations live only in the runtime catalog, so nothing is registered before
initialization. Local saves the selected file for restart after activation; Hosted
resolves its declaration at every start. Startup never upgrades. The active runtime
source cannot be retargeted, disabled, deleted or replaced by changing a registry
default. See [initialization and upgrades](../operations/catalog-migrations.md).

## Register a database

The Admin form accepts the database password directly. The backend creates a
credential through the API CredentialStore and stores its UID on the registration.
Local uses encrypted catalog records; hosted uses managed SDK Secrets. Users do not need to
create the password Secret first. Hosted SDK Secret operations keep their existing
Environment requirement, and the API performs creation and lookup in its own
SDK context. Programmatic registrations can also reference an existing Secret,
as in the example below; the MetaTables client does not fetch credentials.

```python
from metatables import DataSource

source = DataSource.register(
    display_name="Analytics",
    class_type="postgresql",
    configuration={
        "host": "database.example.com",
        "port": 5432,
        "database_name": "analytics",
        "database_user": "metatables",
        "ssl_mode": "verify-full",
        "default_schema": "public",
        "password_secret_uid": "00000000-0000-0000-0000-000000000001",
        "tls_ca_secret_uid": "00000000-0000-0000-0000-000000000002",
    },
)
source.check_connection()
source.configure(storage_access_mode="read_only")
```

Replace the example Secret UIDs with existing accessible Secrets. Optional
`tls_certificate_secret_uid` and `tls_key_secret_uid` configure client TLS.
Plaintext password and TLS fields inside configuration are rejected. The API
accepts a separate write-only `password` field. Secret values are resolved when a
connection is opened and are not cached in the registry or returned by its API.

## Register MySQL or MSSQL

Both use the same opaque password credential UUID field. Install the MySQL Python extra or the
Microsoft ODBC Driver 18 system package on the API server, respectively, before
validating a connection. The MetaTables package includes pyodbc; the Python
client uses HTTP and does not open database connections directly.

```python
from metatables import DataSource

mysql = DataSource.register(
    display_name="Warehouse MySQL",
    class_type="mysql",
    configuration={
        "host": "mysql.example.com",
        "database_name": "analytics",
        "database_user": "metatables",
        "password_secret_uid": "00000000-0000-0000-0000-000000000001",
        "ssl_mode": "verify-full",
    },
)
mysql.check_connection()

mssql = DataSource.register(
    display_name="Warehouse SQL Server",
    class_type="mssql",
    configuration={
        "host": "sqlserver.example.com",
        "database_name": "analytics",
        "database_user": "metatables",
        "password_secret_uid": "00000000-0000-0000-0000-000000000001",
        "encrypt": True,
        "trust_server_certificate": False,
    },
)
mssql.check_connection()
```

Use the editable [registration examples](../examples/data_sources/README.md) to
supply your own host, database, user and Secret UIDs. MySQL's schema is its database
name. SQL Server's default schema is `dbo`; its certificate trust is configured on
the API server.

## Manage registrations

In hosted mode, MetaTables Admin's Data Sources page supports registration, configuration,
validation, disablement and removal of additional sources. The runtime source is
declared by the deployment. It binds the shared database backend contract. Existing roles and grants authorize operations. Optional database features,
such as Timescale hypertables, are resolved on that source at invocation; there
is no static DataSource feature flag list.

All admitted callers can inspect public source metadata. Application admins can
manage registrations and view their configuration and Secret UIDs. Selecting a
new default is also an admin action. The local SQLite file path remains hidden
even from admins on the DataSource record and summary routes.

`read_only` prevents storage writes; `disabled` prevents storage access and Secret
resolution. Connection validation updates the source's availability status. The
admin can correct configuration and validate again. Referenced sources and the
current default cannot be removed. Source removal preserves database contents and
credential records. Entering a replacement password in the edit form creates a new
credential reference; leaving it blank preserves the existing password. API clients
can also update the referenced platform Secret or select another Secret UID.

The management API is `/data-sources/`, `/data-sources/{uid}/` and
`POST /data-sources/{uid}/validate/`. Local SQLite file paths are controlled by the
API launcher and are never writable through these endpoints. Local metadata has
`can_manage: false`; Admin displays the fixed workspace source without registration
or mutation controls. Hosted APIs reject SQLite sources even if a row was restored
or inserted directly into the catalog.

To use the Admin site, open **Data Sources → Register source**, select the engine,
fill in the connection fields and password, and save. Engine selection sets the
port, schema and TLS defaults. Optional TLS certificate fields reference existing
Secrets. Open the saved registration and choose **Test connection**. Its detail
page shows connection metadata, availability and storage access mode.
Use the configuration form to replace connection settings, select **Disable** to
block new connections, or **Remove registration** to remove an unused entry.
