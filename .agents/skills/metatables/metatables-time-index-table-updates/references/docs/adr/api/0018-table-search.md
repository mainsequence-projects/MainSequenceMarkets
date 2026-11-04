# ADR 0018: Table search by meaning and columns

Date: 2026-10-04

Status: Accepted.

Implementation status: implemented. Tests cover documents, rankings, visibility,
freshness and the client against isolated SQLite catalogs, with a fake embedder for
the meaning ranking. PostgreSQL, MySQL and SQL Server catalogs have not been run
against their containers.

Owner: MetaTables API. The Python client, CLI and client skills expose it; the
Admin uses the same route.

Related decisions: [ADR 0001](0001-unified-api-storage-and-local-sqlite.md) (one
execution path for local SQLite and hosted PostgreSQL),
[ADR 0002](0002-application-administration-and-table-ownership.md) (hidden tables
are not discoverable through search) and
[ADR 0010](0010-import-external-tables-and-views.md) (imported tables enter the same
catalog).

## Context

In the previous platform backend, every MetaTable had a stored search document and a pgvector
embedding (`TableSearchIndex`). `description-search` ranked tables by trigram
similarity plus cosine similarity, and agents used it first through the SDK, the
CLI, an exploration skill and an MCP tool. That system was retired with the move
to this service.

Today the catalog stores the same metadata (table and column descriptions,
labels, namespace), but search is a substring match on identifier and physical
name, plus a separate column search. A table's description is never searched.
The client's `description_search` and `refresh_table_search_index` call routes
that do not exist.

Catalogs will hold hundreds to thousands of tables. At that size neither a person
nor an agent can scan the list, so the API must find candidates by meaning, and
the words of a query often match different parts of a table: "bond prices"
should find a table described as Mexican sovereign bonds whose column is
`clean_price`.

## Decision

One search route ranks the tables the caller can see by two signals and returns
each hit with the columns that matched.

| Part | Rule |
| --- | --- |
| Document | One per table, built only from that table's own metadata: identifier, physical name, table description, labels, time index and cadence, namespace and its description, and every column's name, type, logical name, label and description. Never another table's name. |
| Keyword ranking | BM25 over the document. Identifiers are split (`clean_price`, `closePrice` → `clean`, `price`, `close`) and words are stemmed (`prices` → `price`), so query words match columns as well as descriptions. Table fields weigh more than column fields. |
| Meaning ranking | The document is cut into chunks that fit the model's 512-token window: one with the table header, then groups of columns each repeating the table header. A table scores its best chunk's cosine similarity, so a wide table is not diluted. |
| Result | The two rankings are merged with reciprocal rank fusion. Each hit carries the normal table projection, its score and `matched_columns`. |
| Visibility | The grant predicate selects the candidate tables first; ranking never sees a hidden table. |

`GET /meta-tables/search/?q=&limit=` accepts the existing list filters and is
also served under `/time-index-meta-tables/`.

### How the document is built

![A metadata write rebuilds the table's search document in the same catalog transaction from the table, its labels, its namespace and every column, never from other tables' names. The document and its hash are stored and keyword terms are derived at once; in the background the document is cut into 512-token chunks, embedded and stored one vector per chunk.](0018-search-document-pipeline.svg)

*Figure 1. The document is current when the write commits; its vectors follow.*

The document has three sections in a fixed order. Empty fields are left out
rather than written as "Unknown", so they add no noise to either ranking. The
existing `GET /meta-tables/{uid}/search-document/` route returns this document.

### Sample

A time-index table registered with these descriptions:

```text
# Table
Identifier: valmer_mx_sovereign_eod
Physical table: public.valmer_mx_sovereign_eod
Description: Daily end-of-day valuations of Mexican government debt
(M Bonos, Udibonos and CETES) from the Valmer vector.
Labels: fixed-income, mexico, end-of-day
Time index: valuation_date, cadence 1d

# Namespace
Name: valmer
Description: Data delivered by Valmer, the Mexican valuation vendor.

# Columns
valuation_date (date): Valuation date. Business day the values apply to.
isin (string): ISIN. Bond identifier.
instrument_type (string): Instrument type. M Bono, Udibono or CETE.
clean_price (float): Clean price. Price excluding accrued interest, per 100 nominal.
dirty_price (float): Dirty price. Clean price plus accrued interest, per 100 nominal.
ytm (float, logical name yield_to_maturity): Yield. Annual yield to maturity, in percent.
asset_uid (uuid): Asset. Asset this valuation belongs to.
```

`asset_uid` is a foreign key. Only the column's own description appears; the
name of the table it references does not.

The table has seven columns, so it produces two chunks. Chunk 0 is the `# Table`
and `# Namespace` sections. Chunk 1 repeats the identifier and description, then
lists all seven columns. A 200-column table would produce about a dozen column
chunks.

Searching "bond prices" reaches this table through both rankings, although
neither word is in its identifier:

| Query word | Keyword ranking | Meaning ranking |
| --- | --- | --- |
| bond | No match: "Bonos" stems to `bono` | Chunk 0: "Mexican government debt" |
| prices → `price` | `clean_price`, `dirty_price` (split identifiers) | Chunk 1: the clean and dirty price lines |

The hit returns `matched_columns: [clean_price, dirty_price]`.

The sample's description leaves out the word "bonds" to show the meaning ranking
at work. The description rules in the skill require it, so a table written by
those rules matches "bond" by keyword as well.

### Columns

Matching on columns is part of table ranking, not a separate mode. A query whose
words land in the description and in a column name ranks above a table that
matches only one of them. `matched_columns` tells the reader why a table was
returned: it lists the columns whose name or logical name contains a query word.
Words in a column's description count toward ranking but do not make the column
matched, because descriptions mention the table's subject in nearly every column. The column-only `column-search` route stays for schema lookups.

### Embeddings

The API embeds with a pinned local ONNX model, `BAAI/bge-small-en-v1.5` (MIT, 384
dimensions, 67 MB), through `fastembed`. It runs offline, needs no platform
service and works the same locally and hosted. Search is English-only: metadata
and queries are expected in English.

The model id is a code constant stored with every vector. Changing it makes
every vector stale and triggers a full re-embed. The model is loaded lazily in
the API process and downloaded into the MetaTables cache on first use. Until it
is available, search runs on keywords only and says so with `semantic: false` in
the response.

### Index lifecycle

A new system migration adds two catalog tables:

- `meta_table_search_document`: table UID, document, document hash, updated time,
  and the model and document hash its vectors embed.
- `meta_table_search_vector`: table UID, chunk number, model, document hash and the
  vector as float32 bytes.

Every write that changes a table's metadata (register, patch, label change,
import, finalize, contract update, namespace description change) rewrites the
document in the same catalog transaction, so keyword search is never stale. A
background worker in the API process embeds documents whose hash or model does
not match their vectors. The upsert is keyed by hash, so two replicas doing the
same work is harmless. The worker also builds documents for tables that have none.
The migration builds documents for existing tables. There is no manual refresh
endpoint. `METATABLES_SEARCH_EMBEDDINGS=off` keeps the model from loading.

Ranking runs in the API process with NumPy over a per-process cache of documents
and vectors, refreshed by hash. At 10,000 tables of three chunks each the vectors
take about 46 MB per process, and a query takes a few milliseconds plus the grant
query. Above roughly 100,000 tables, move the vectors to pgvector on hosted
PostgreSQL; the route does not change.

### Better metadata in

- Registering a table that already exists updates its descriptive metadata from
  the request: description, labels, and each column's label, description and
  logical name. Identity, namespace and physical binding do not change. Today
  registration returns the existing row unchanged, so a description improved in
  code never reaches the catalog. With this rule, the catalog sync in
  `metatables migrations upgrade` keeps the catalog equal to the model.
- Labels and the namespace description enter the document.
- Namespace description becomes writable: `PATCH /namespaces/{uid}/` by the
  namespace's Writers.
- SQLAlchemy `comment=` and `doc=` fill a missing column or table description;
  `info={"description": ...}` still wins.
- Import and refresh of external tables read database comments
  (PostgreSQL `obj_description`/`col_description`, MySQL `TABLE_COMMENT`/`COLUMN_COMMENT`,
  SQL Server `MS_Description`) when the catalog has no description.

### Client, CLI and skills

- `MetaTable.search(q, limit=..., **filters)` and the same on `TimeIndexMetaTable`
  return a `TableSearchResult` with `semantic` and `hits`; each hit has `table`,
  `score` and `matched_columns`. `description_search` and
  `refresh_table_search_index` are removed.
- `meta-table search` and `time-index-table search` use the route by default;
  `--mode column` keeps column search. The trigram and embedding flags are removed.
- The `.agents/skills/client/metatables-table-discovery/SKILL.md` client skill
  has two parts. The first tells agents how to search: query
  phrasing, variants, reading `matched_columns`, and never creating a duplicate
  when nothing matches. The second is the authoritative rule set for table
  descriptions, column `info`, labels and identifiers on `PlatformManagedMetaTable`,
  `PlatformTimeIndexMetaTable` and external models. The table, time-index and
  migrations skills link to it instead of carrying their own description
  guidance, and drop "description search is not supported". The client example
  tables are rewritten to follow it.

## Not adopted

- **The platform's embedding service.** It is an internal Celery task in
  the platform backend, and local MetaTables must work without the platform.
- **pgvector and database full-text search now.** They would give SQLite and
  PostgreSQL different behavior and need containers to test. In-process ranking
  covers the expected catalog size.
- **A multilingual model.** Metadata and queries are English.
  `paraphrase-multilingual-MiniLM-L12-v2` would triple the download and limit
  chunks to 128 tokens.
- **LLM-written descriptions.** The platform backend carried a Gemini prompt for this, but
  the deterministic document always took precedence and the prompt never ran.
- **Foreign-key targets in the document.** Naming a hidden target table would
  reveal it through ranking or snippets. The schema graph shows relationships to
  visible tables.

## Verification

A relevance fixture of about 2,000 generated tables with labeled queries,
including column-driven ones such as "bond prices" → a table with `clean_price`,
checks recall at 10 and that a hidden table never appears. A latency test checks
the route at 5,000 visible tables on SQLite. Both run without containers.

Verified on 2026-10-04 against a copy of a developer's local runtime (289 tables,
2,890 columns, catalog revision 0010) served by the local launcher: Settings'
migration applied `0011_table_search` and built all 289 documents in about half a
second; the worker downloaded the model and embedded every table in about 40
seconds; warm searches took 10–30 ms. A description edit was searchable by
keywords in the same transaction and re-embedded within a second. The CLI and the
Python client returned the same rankings. The 209 imported tables in that runtime
have no descriptions and Spanish column names, so English search reaches them only
through their names until they are described.
