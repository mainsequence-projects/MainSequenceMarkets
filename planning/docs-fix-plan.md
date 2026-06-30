# Documentation Fix Plan — `ms-markets`

> Status: **ALL PHASES DONE** (2026-06-30). Audit clean (0 orphans, 0 broken
> links across 245 links); `mkdocs build --strict` passes.
> This file lives outside `docs/` on purpose, so it is
> never published or counted as an orphan. The recurring discipline that keeps
> the docs aligned afterward is `.agents/prompts/keep-docs-current.md`.

## Problem statement

The docs read as a patchwork rather than one continuous site. Individual pages
are mostly high quality and well cross-linked *within* a section; the
discontinuity comes from the **seams between sections**: orphaned files, an
aspirational-yet-overstuffed Tutorial, a split ADR tree, content duplicated
between an index and its children, and heavy copy-pasted boilerplate. A
link/orphan audit found **0 broken links** (144 checked) — so this is purely a
structure/continuity problem, not link rot.

## Locked decisions

- **Maintenance artifact**: a read-on-demand prompt at
  `.agents/prompts/keep-docs-current.md` (built). Complements, does not replace,
  the per-change `library_maintenance` skill.
- **Sub-docs**: `msm_portfolios` and `msm_pricing` are promoted to **top-level
  nav sections** at parity with `msm` (not buried under Knowledge).

## Guiding principles

1. One canonical home per fact; everything else links to it.
2. Reference vs. narrative are different jobs — Knowledge/package sections are
   reference; Tutorial is the narrative spine.
3. Nav is the source of truth for what is published; nothing in `docs/` is left
   un-navved.
4. Enforce the page template you already documented, or delete the promise.

## Target information architecture

```
Home                 → what/why in one screen, links out (no deep content)
Getting Started      → install + a first example that runs
Core Concepts (NEW)  → canonical runtime model (row vs *Table vs DataNode,
                       start_engine = attachment not schema, migrations-first,
                       MSM_AUTO_REGISTER_NAMESPACE). Everything else links here.
Tutorial             → linear chain w/ "Next →": assets → calendars → accounts
                       → portfolios → pricing
msm                  → core package reference
msm_portfolios       → TOP-LEVEL section, parity with msm
msm_pricing          → TOP-LEVEL section, parity with msm
FastAPI v1           → thin overview + one reference page per route group
Command Center       → unchanged (already clean)
Architecture / ADR   → ALL ADRs, one tree (docs/ADR/, API ADRs under
                       docs/ADR/fast_api/v1/)
Reference            → mkdocstrings autodoc
Changelog            → snippet include of root CHANGELOG.md (already correct)
```

---

## Phase 0 — Decisions to lock first

| Decision | Choice |
|---|---|
| ADR home | `docs/ADR/` is the single root; API ADRs under `docs/ADR/fast_api/v1/` |
| `docs/implementation_tasks/` | Move out of `docs/` to `planning/implementation_tasks/` (or delete if shipped) |
| Tutorial structure | Linear multi-page narrative; `market_workflows.md` becomes the asset/calendar chapter |
| Package sub-docs | Top-level sections for `msm_portfolios` and `msm_pricing` |

---

## Phase 1 — Remove orphans & dead weight  (effort S · risk low)

- [x] **1.1** Verify each `docs/implementation_tasks/` file is shipped, then move
  the directory to `planning/implementation_tasks/` (outside `docs_dir`) or
  delete completed ones.
  - 6 files: `fast_api/{portfolio_delete_cleanup,portfolio_routes,portfolio_signal_metadata_route,pricing_market_data_routes}.md`,
    `platform/{refactor_to_sdk_metatable_migration_helpers,remove_markets_metatable_catalog}.md`
- [x] **1.2** `knowledge/msm_portfolios/virtualfunds/index.md` is an orphaned
  vestigial redirect stub. **Delete it** and repoint the "Virtual Funds Boundary"
  link in `knowledge/msm_portfolios/index.md` to
  `../msm/accounts/virtual_funds.md`.
- **Acceptance**: orphan audit prints empty; `find docs -path '*implementation_tasks*'` is empty.

## Phase 2 — Consolidate the ADR tree  (effort S · risk low–med: link updates)

- [x] **2.1** Move `docs/fast_api/v1/ADR/0001-calendar-crud-route.md` →
  `docs/ADR/fast_api/v1/0001-calendar-crud-route.md`; delete the empty
  `docs/fast_api/v1/ADR/`.
- [x] **2.2** Update inbound references: `mkdocs.yml` (lines ~40–42, ~96–99),
  the "Route ADRs" paths in `docs/fast_api/v1/index.md`, and add the Calendar
  CRUD ADR to the "FastAPI Decisions" list in `docs/ADR/README.md`.
- [x] **2.3** (optional) Number the two unnumbered FastAPI ADRs
  (`fixed-income-pricer-api.md`, `command-center-adapter-discovery.md`) so the
  tree sorts.
- **Acceptance**: `find docs -type d -name ADR` returns only `docs/ADR`; README lists all ADRs; audit still 0 broken.

## Phase 3 — Extract repeated boilerplate  (effort M · risk low)

- [x] **3.1** Create `docs/concepts.md` ("Core Concepts / Runtime Model") as the
  single canonical explainer (row vs `*Table` vs DataNode; `start_engine()`
  semantics; migrations-before-runtime; `MSM_AUTO_REGISTER_NAMESPACE`).
- [x] **3.2** Replace the duplicated paragraphs in `index.md`,
  `getting-started.md`, `knowledge/index.md`, `tutorial/index.md`, and concept
  pages with a one-line rule + link to `concepts.md`. Keep code snippets local.
- [x] **3.3** Add `concepts.md` to nav after Getting Started.
- **Acceptance**: the phrase "do not register or attach MetaTables on first use" appears once (the canonical page).

## Phase 4 — Promote & build out package sections  (effort L · risk med)

> New phase from the top-level-sections decision. Do after the ADR tree settles
> and before the tutorial rebuild (the tutorial's portfolio/pricing chapters
> link into these sections).

- [x] **4.1** Restructure nav so `msm`, `msm_portfolios`, `msm_pricing` are peer
  top-level sections (move them out from under "Knowledge"; fold the Knowledge
  overview into Core Concepts or a short landing).
- [x] **4.2** Bring each package to the per-package contract (overview + concept
  pages + tutorial chapter link + ADR back-links + cross-package
  `Related Concepts`):
  - `msm_portfolios` — currently 2 thin pages; flesh out portfolio concepts.
  - `msm_pricing` — currently 1 page; split into concept pages (instruments,
    curves, fixings, market-data sets, valuation).
- [x] **4.3** Ensure every concept page follows the template and has a working
  `Related Concepts` footer that links across package boundaries.
- **Acceptance**: per-package coverage diff shows parity; all pages navved; strict build clean.

## Phase 5 — Rebuild the Tutorial as a narrative  (effort L · risk med)

- [x] **5.1** De-duplicate `tutorial/index.md` vs `tutorial/market_workflows.md`
  (they heavily overlap today). Pick one owner per workflow.
- [x] **5.2** Split into linear chapters with "Next →" links:
  `01-assets`, `02-calendars`, `03-accounts`, `04-portfolios`, `05-pricing`.
- [x] **5.3** Move "Library Maintenance Workflow" out of the tutorial (it's
  contributor guidance) into `AGENTS.md` / a maintenance page.
- [x] **5.4** Update nav; remove all "this section will contain / coming soon"
  placeholder text.
- **Acceptance**: no placeholders; each chapter ≤ ~1 screen prose + code; unbroken "Next" chain.

## Phase 6 — Fix the FastAPI section  (effort M · risk med)

- [x] **6.1** Make `fast_api/v1/index.md` a thin overview (scope, bootstrap,
  discoverability) that links to per-route child pages; move the inline endpoint
  catalog into the child pages where it belongs.
- [x] **6.2** Rename the mislabeled "Route ADRs" heading → "Route Reference";
  keep genuine ADR links in a separate short "Design decisions" list.
- **Acceptance**: each endpoint documented in exactly one page; index is overview-only.

## Phase 7 — Enforce the Knowledge/concept template  (effort S–L · risk low)

- [x] **7.1** Reconcile the documented "Documentation Pattern" with reality —
  either relax the promise to the actual common shape (Scope → Tables/Relations
  → API → Extension Rules → Related Concepts) requiring only **Scope** +
  **Related Concepts** everywhere, or reshape pages to the strict 5 headings.
- [x] **7.2** Guarantee every concept page has a `Related Concepts` footer.
- **Acceptance**: template promise and pages match.

## Phase 8 — Verification gate  (run after each phase)

- [ ] `mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site` passes.
- [ ] Orphan + broken-link audit prints empty.
- [ ] Boilerplate grep shows the canonical phrase once.
- [ ] (optional) Add the audit script to `scripts/` and/or a CI step.

---

## Suggested execution order & risk

| Phase | Effort | Risk | Sequence |
|---|---|---|---|
| 0 Decisions | — | — | first (done) |
| 1 Orphans | S | low | parallel-safe |
| 2 ADR consolidation | S | low–med | parallel-safe |
| 3 Boilerplate extraction | M | low | before 4 & 5 |
| 4 Package sections | L | med | after 2–3, before 5 |
| 5 Tutorial rebuild | L | med | after 3–4 |
| 6 FastAPI de-dupe | M | med | parallel-safe |
| 7 Template enforce | S–L | low | last |
| 8 Verification | S | — | continuous |

Phases 1, 2, 6 are independent. Phase 3 lands before 4 and 5. Phase 4 before 5.
Phase 7 last, once page shapes settle.
