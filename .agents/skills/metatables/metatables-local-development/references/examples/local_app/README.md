# Complete local application example

This example ships in the Python package. Run it from **your application's Git
checkout**; no MetaTables source checkout or table UID is required. The checkout
needs a commit and an `origin` remote. Use Python 3.13+ on macOS or Linux.

```bash
python -m pip install mainsequence-metatable
mainsequence login
metatables init --local
metatables serve --local --admin
```

Admin needs Node.js 22.12+ (or 20.19+) and npm. It uses the existing Vite development
mode. Source is downloaded only if the pinned installation is missing; completed
dependencies are reused. The repository currently requires GitHub access: use an
existing authenticated `gh` session or `--admin-path /path/to/prepared/Admin`.
Omit `--admin` for a CLI-only workflow.

In another terminal in the same project and Python environment:

```bash
metatables --local runtime status
metatables --local runtime initialize
metatables --local migrations upgrade --provider examples.local_app.migrations:migration
python -m examples.local_app
metatables --local meta-table list
```

Expected example output:

```json
[{"key": "hello", "message": "My local MetaTables application"}]
```

The client runs the provider to create the table, then finalizes its catalog binding through the API.
The example resolves that table by identifier, compiles bound SQL for the API's
selected dialect, upserts one note, and reads it back. Ordinary reads and writes use the API; only migrations open the environment database. Repeating it keeps one row. Stop and restart the launcher, then inspect
the existing row before any write:

```bash
python -m examples.local_app --read-only
```

The API retains its selected database across restarts and branches. Initialization
is explicit. `runtime status` and Admin Settings work before system migration.
Native keyring credentials are the default; for a headless machine, configure the
file credential provider as described in the [local runtime guide](../../docs/operations/local-runtime.md#local-credentials).

For your own application, define tables like [Note](tables.py), install the package
containing your [migration provider](migrations/__init__.py) in the application process. See [migration authoring](../../docs/client/define-and-migrate-tables.md).
