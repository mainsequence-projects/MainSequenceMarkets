# Maintaining the documentation

Explain current product behavior in the order a user needs it: concepts, a client
workflow, API behavior, and operations. The overview must stand on its own. Keep
implementation history out of user guides and use version-control history when
investigating past changes.

The Python client and API are separate surfaces. Explain who owns identity,
storage, grants, schema changes, and execution before showing commands. Keep table
UIDs, logical identifiers, physical names, catalog namespaces, and updater hashes
distinct. Describe unsupported behavior explicitly rather than implying that an
inherited method guarantees an endpoint.

## Change workflow

Architecture decisions live under `docs/adr/client/` or `docs/adr/api/`, according
to the component that owns the behavior. Use one project-wide ADR number sequence,
state decision and implementation status separately, and update the ADR index and
site navigation. Link decisions across components instead of mixing client
transport selection with API runtime or storage policy. Keep platform SDK
decisions in the SDK repository.

1. Update behavior and relevant tests together.
2. Update the authored concept/workflow pages and the capability inventory.
3. Keep runnable examples in `examples/` and exercise them in `tests/examples`.
4. Regenerate references and check links, imports, examples, and the site.

```bash
python -m scripts.build_reference
python -m scripts.check_client_api_coverage
python -m scripts.check_boundaries
python -m scripts.check_docs
python -m pytest -q
mkdocs build --strict
```

The reference generator derives HTTP paths and schemas from `create_app`, Python
exports from `metatables.__all__`, and CLI arguments from Typer. Capability status
is maintained deliberately in the inventory because reflection cannot establish
behavioral support. The generator also publishes copies of tested example assets
inside the documentation site; edit their originals in `examples/`.

The test suite rejects stale generated artifacts. The documentation checker
validates local Markdown links, heading links, Python-block syntax, and skill
references. These checks complement behavioral example tests; compiling a code
block alone does not establish that its network prerequisites exist.

## Client usage skills

The skills under `.agents/skills/client/` guide applications consuming the installed
MetaTables Python client. Their scope is application authoring and client usage.
Client-library development, this repository's tooling, and API/server implementation
belong to their component documentation and project instructions.

| Skill path | Client workflow |
| --- | --- |
| `.agents/skills/client/metatables-local-development/SKILL.md` | Local-first application development, runtime/DataSource checks, isolated verification and explicit return to the environment. |
| `.agents/skills/client/metatables-meta-tables/SKILL.md` | SQLAlchemy contracts, external registration, governed queries and client access operations. |
| `.agents/skills/client/metatables-migrations/SKILL.md` | Alembic providers, offline revisions, approved API-side execution and migration recovery for managed application tables. |
| `.agents/skills/client/metatables-time-index-table-updates/SKILL.md` | Producers, dependencies, incremental frames and existing-table readers. |

Keep invocation names stable and folder names aligned with their skill names.
Preserve the distinct workflows and update sibling/documentation references when
moving files. Guides and examples referenced by these skills belong to the
MetaTables source distribution; a consuming application's working directory may
not contain them. Use the matching client version's supported-capability inventory
when deciding whether an operation can be promised.

`metatables copy-metatables-skills` uses the SDK scaffold-copy helper to deliver
only these client skills into a consuming project's `.agents/skills/metatables/`
namespace. The package build and editable CLI use the same resource builder.
It snapshots the referenced guides/examples and their linked local documents
under each skill's `references/` directory; edit the original files above rather
than generated bundle contents. Include supporting files in the skill folder
when they are maintained specifically for that skill. The installed-wheel test
and distribution checker verify delivery outside this checkout.
