# Import existing tables and views

Import records definitions in the current MetaTables catalog. The source keeps
ownership of its data and schema. A read-only external source needs SELECT and
metadata visibility for the objects to import; MetaTables creates nothing there.

## Discover and import

An administrator can open **Data Sources → source → Import** to automatically
load the available tables and views. The source's configured schema is the default;
enter another schema and choose **Load schema** to change it. Use the searchable
**Available in source** and **Selected for import** lists to choose individual
objects or add all shown objects, then choose **Import selected**. Already imported
objects are marked and can be selected to refresh their definitions. Objects that
cannot be refreshed are disabled with a reason.

The site imports exactly the selection, without adding foreign-key targets. A
foreign key whose target is outside the current batch is reported as a warning.
Python retains preview and foreign-key expansion as defaults; set
`follow_foreign_keys=False` for the same exact-selection behavior:

```python
from metatables import MetaTable

source_uid = "your-registered-data-source-uuid"
preview = MetaTable.import_from_data_source(source_uid)

result = MetaTable.import_from_data_source(
    source_uid,
    relation_names=["positions", "current_positions"],
    namespace="research",
    follow_foreign_keys=False,
    dry_run=False,
)
```

`strict=True` prevents all catalog changes if any relation cannot be imported.
With `strict=False`, valid relations can be committed and failures are reported
individually. Inspect `committed`, `ok`, `relations`, `warnings`, and `counts`.
Repeated imports reuse physical identities; refreshing preserves UIDs, grants,
labels, namespace, descriptions, and ownership. Imports create relational
MetaTables, including when the inherited method is called on TimeIndexMetaTable.

Use exact physical names, including case and spaces. A view is recorded as
`table_contract.physical.relation_kind="view"`. Views and tables without primary
keys are supported. Each import request permits 200 relations including foreign-key
expansion, with a 60-second deadline. Discovery lists names independently of that
batch limit. The site submits larger selections in sequential batches of up to 200
and shows progress. If a batch fails, completed batches remain imported and the
remaining objects stay selected for retry. Strict atomicity applies per batch.
Within each request, metadata inspection shares a source connection and discovery
result. A fresh bulk metadata check precedes publication. External import checks
SELECT permission without fetching source rows; reading and serializing data
happens through the Rows view or `read_rows()`.
System/catalog objects, materialized views, synonyms and foreign tables are
excluded from this workflow.

## Read rows and refresh definitions

Readers and Writers can open the table's **Rows** tab. External DataSources also
provide a registered table/view picker in their **Query builder** tab. Python
uses the same bounded endpoint:

```python
from metatables import MetaTable

table = MetaTable.get_by_uid("imported-table-uuid")
page = table.read_rows(
    columns=["symbol", "quantity"],
    filters=[{"column": "symbol", "operator": "eq", "value": "SPY"}],
    order_by=[{"column": "symbol", "direction": "asc"}],
    limit=100,
)
print(page["rows"])

# Requires Writer access; refreshes metadata only.
table.introspect()
```

Supported scalar predicates are `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in`, and
`is_null`. JSON and binary columns support null predicates only. Return values
include ISO date/time strings and base64 binary values. Reads default to 100 rows,
are capped at 1,000 rows and 8 MiB, and never accept SQL fragments, joins, or
caller-supplied physical names. New physical columns remain hidden until refresh.
The Rows tab's **Refresh definition from source** action requires Writer access.
Pagination over changing data or without a unique ordering is not a stable snapshot.

External reads use the registered source account after checking MetaTable or
namespace grants. These application grants do not create roles or permissions in
the external database. Runtime SQL security can remain uninitialized while
external imports and reads work. Arbitrary SQL remains restricted to the selected
runtime DataSource and its database-enforced caller permissions.

For SQLite runtime views, bounded reads allow only the approved view's output.
Arbitrary SQL still requires grants on its underlying tables: SQLite's view-origin
callback can be spoofed with a CTE name and must not grant that access implicitly.

## Ownership and lifecycle

The external owner applies physical schema changes. Import refresh or introspect
then updates MetaTables definitions and projections. Stale scan results are only
visibility warnings; they never delete a registration. Ordinary unregistration
removes catalog metadata and preserves the physical table/view. Dependency and
protection checks still apply. Views never receive write privileges.

If authoring a contract for an existing table on the selected runtime source,
[the external-table example](../examples/external_table.py) remains available.
Use import for discovery and for registered non-runtime sources. Raw SQL and
external physical writes are outside this workflow.
