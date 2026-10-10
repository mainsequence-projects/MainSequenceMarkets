---
name: metatables-table-discovery
description: "Find existing MetaTables and time-index tables by meaning with table search, and write the table descriptions, labels and column metadata that make tables findable. Authoritative for every description, label and column `info` authored on MetaTables SQLAlchemy models in consuming applications. Excludes API/server changes, client-library implementation and table storage design."
---

# Finding tables and writing findable metadata

Table search ranks the tables you can read using one document per table, built
from the table's own metadata: identifier, description, labels, namespace, time
index and cadence, and every column's name, type, label, description and logical
name. What you write on a model is exactly what search reads. The decision is
`docs/adr/api/0018-table-search.md`.

This skill is authoritative for descriptions, labels and column metadata. Other
MetaTables skills defer to it. Storage design (physical names, grain, foreign
keys, indexes) stays with the [table skill](../metatables-meta-tables/SKILL.md);
schema evolution with the [migrations skill](../metatables-migrations/SKILL.md).

In a copied skill, resolve `docs/` paths relative to this skill's `references/`
directory.

## Part 1: Find a table

Search before writing code that reads data the user describes in words, and
before authoring a new table. Reusing a table beats creating a near-duplicate,
which also splits future search results.

```python
from metatables import MetaTable, TimeIndexMetaTable

result = TimeIndexMetaTable.search("bond prices", limit=10)
for hit in result.hits:
    print(hit.table.identifier, hit.score, hit.matched_columns)
```

```bash
metatables time-index-table search "bond prices"
metatables meta-table search "account balances" --filter namespace=ledger
```

`MetaTable.search` covers every table; `TimeIndexMetaTable.search` only
time-index tables. Both accept the list filters (`namespace`, `labels__in`,
`data_source_uid`, ...) to narrow a search you have already started.

### Write the query

- Use a short English noun phrase of domain words: what the rows are and the key
  measure. `bond prices`, `fx spot rates`, `portfolio positions`. Not a question,
  not SQL, not a physical table name.
- Run two to four variants before concluding anything: a synonym (`sovereign
  debt`), a market or vendor term (`M Bonos`, `CETES`, `Valmer`), and column words
  (`clean price`, `yield`).

### Read the results

- `matched_columns` lists the columns whose name or logical name contains a query
  word. A table that matches both in its description and in its columns is usually
  the right one.
- `result.semantic` is `false` while the embedding model is unavailable; ranking
  is then by keywords only, so try the exact words likely to appear in names and
  descriptions.
- Before using a candidate, read its `description` and columns in the hit to
  confirm the grain, the time index, the cadence and the units.
- Results contain only tables you can read. When the data surely exists but
  nothing matches, ask the user for the owner or identifier. Do not create a
  duplicate table.
- Use `MetaTable.column_search(q)` only for a pure column-name lookup.

Do not list every table and scan it, use the list filter `q` for meaning (it
matches identifier and physical name only), or conclude a table is absent from
one query.

## Part 2: Write findable metadata

These rules apply to every `PlatformManagedMetaTable`,
`PlatformTimeIndexMetaTable` and externally registered SQLAlchemy model.

| Search reads | Write it in |
| --- | --- |
| Table description | `__metatable_description__` |
| Labels | `__metatable_labels__` |
| Identifier | `__metatable_identifier__` |
| Namespace | `__metatable_namespace__` |
| Column label, description, logical name | `mapped_column(..., info={"label": ..., "description": ..., "logical_name": ...})` |
| Time index and cadence | `__time_index_name__`, `__index_names__`, `__cadence__` |

Use only these attributes. Do not put metadata in SQLAlchemy `comment=` or `doc=`:
they are fallbacks for imported tables, and `info` wins over them.

### Table description

Required on every table. One to three sentences, at most 500 characters, in
English, in this order:

1. **Grain.** What one row is: "One row per ISIN per valuation date."
2. **Subject.** The plain English words a searcher would type, then the domain or
   vendor terms: "End-of-day prices and yields of Mexican government bonds (M
   Bonos, Udibonos and CETES)". Always include the plain English noun even when a
   vendor term is standard: keyword search matches words, and "Bonos" does not
   match "bond".
3. **Source and coverage.** Who produces it and from what: "from the Valmer daily
   price vector".
4. **Timing,** for time-index tables: when rows arrive, in words: "published after
   the Mexican market close".

Never:

- start with "Table of", "This table contains" or "Data for";
- repeat the identifier, the physical name or the column list;
- name another table. Say what the related thing is ("the asset each valuation
  belongs to"). A table name in prose can reveal a table the reader may not see;
- write placeholders (TBD, Unknown, n/a), ticket numbers, people's or customers'
  names, credentials or URLs carrying tokens;
- describe implementation: updater classes, hashes, Alembic.

### Columns

Every column gets `info` with `label` and `description`, including the primary
key, the time index and the identity dimensions.

- `label`: one to four words, sentence case, no units: `"Clean price"`.
- `description`: one sentence giving the meaning plus whatever a reader needs to
  use the value correctly:
  - unit, currency or scale: "per 100 of nominal", "in MXN", "in percent: 5.25
    means 5.25%";
  - identifier scheme: "ISIN", "Main Sequence asset UID";
  - allowed values of a code: "M Bono, Udibono or CETE";
  - for times, which moment and timezone: "valuation business day at 00:00 UTC";
  - what null means, when the column is nullable;
  - the sign convention, where one applies.
- Foreign-key columns describe what the referenced thing is, never the referenced
  table's name.
- Name new columns in full snake_case words (`clean_price`, not `cln_px`). Search
  splits names into words, so each word becomes searchable.
- `logical_name` only when the physical name is an abbreviation or vendor code you
  cannot change, typically on an external table: a column `ytm` gets
  `info={"logical_name": "yield_to_maturity", ...}`.

### Labels

- Two to six labels, lowercase and hyphenated: `fixed-income`.
- Draw them from these facets: domain or asset class (`fixed-income`, `fx`,
  `equities`, `accounting`), geography (`mexico`, `global`), data kind (`prices`,
  `reference-data`, `positions`, `transactions`, `risk`), and source (`valmer`,
  `banxico`) when the source is not the namespace.
- Reuse labels you see on existing tables in search results instead of creating
  near-duplicates (`fixed_income` next to `fixed-income`).
- Do not repeat the namespace or the cadence as a label.

### Identifier and namespace

- `__metatable_identifier__` is `<namespace>.<concept>` in full words:
  `valmer.mx_sovereign_bond_prices`. It is identity and never changes after the
  table is published.
- `__metatable_namespace__` is the owning application or source, not a SQL schema.
  Its description (one or two sentences about the application or source) is
  written once by the namespace's Writer; do not repeat it in table descriptions.

### Time-index tables, in addition

- The grain sentence matches `__index_names__`: `["time_index", "isin"]` → "One
  row per ISIN per valuation date."
- Declare `__cadence__` whenever the interval is stable.
- The time index column's description says which moment it is (observation,
  valuation, publication or effective date), its timezone and, for daily data,
  the day convention.

### Example

```python
from datetime import datetime

from sqlalchemy import DateTime, Float, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from metatables import PlatformTimeIndexMetaTable, schema_table_name


class Base(DeclarativeBase):
    metadata = MetaData()


class SovereignBondPrice(PlatformTimeIndexMetaTable, Base):
    __tablename__ = schema_table_name("valmer", "mx_sovereign_bond_prices")
    __metatable_namespace__ = "valmer"
    __metatable_identifier__ = "valmer.mx_sovereign_bond_prices"
    __metatable_description__ = (
        "One row per ISIN per valuation date. End-of-day prices and yields of "
        "Mexican government bonds (M Bonos, Udibonos and CETES) from the Valmer "
        "daily price vector, published after the Mexican market close."
    )
    __metatable_labels__ = ["fixed-income", "mexico", "prices"]
    __time_index_name__ = "time_index"
    __index_names__ = ["time_index", "isin"]
    __cadence__ = "1d"

    time_index: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        info={"label": "Valuation date",
              "description": "Business day the prices apply to, at 00:00 UTC."},
    )
    isin: Mapped[str] = mapped_column(
        String(12), nullable=False,
        info={"label": "ISIN", "description": "ISIN of the bond."},
    )
    instrument_type: Mapped[str] = mapped_column(
        String(16), nullable=False,
        info={"label": "Instrument type",
              "description": "Bond family: M Bono, Udibono or CETE."},
    )
    clean_price: Mapped[float] = mapped_column(
        Float, nullable=False,
        info={"label": "Clean price",
              "description": "Price excluding accrued interest, per 100 of nominal, in MXN."},
    )
    dirty_price: Mapped[float] = mapped_column(
        Float, nullable=False,
        info={"label": "Dirty price",
              "description": "Clean price plus accrued interest, per 100 of nominal, in MXN."},
    )
    yield_to_maturity: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        info={"label": "Yield to maturity",
              "description": "Annual yield to maturity in percent; null when Valmer publishes no yield."},
    )
```

### When metadata changes

The model is the source of truth. Edit the model and run `metatables migrations
upgrade`: its catalog sync updates the description, labels and column metadata of
tables that already exist. A metadata-only change needs no Alembic revision.
Re-run the registration of an external table after changing its model. Do not
`patch` the description of a table that has a model; the next sync replaces it.
Use `table.patch(description=..., labels=[...])` only for imported tables with no
model.

## Validation

Before finishing, check every table and column you authored against Part 2:
four-part description, two to six labels, `label` and `description` on every
column. After `metatables migrations upgrade`, search for each new table with two
phrases a user would type; it should appear among the first results. State
whether you ran that search or only checked the model.
