---
name: keep-docs-current
kind: prompt
description: >
  Read-on-demand prompt for auditing and realigning the ms-markets documentation so it
  reads as one continuous, well-linked site instead of a patchwork. Run it whenever you
  want to "keep documentation current" — after a batch of changes, before a release, or
  on a periodic sweep. It complements (does not replace) the library_maintenance skill:
  that skill keeps each individual change in sync; this prompt keeps the whole docs tree
  structurally coherent.
---

# Keep Documentation Current

You are auditing and repairing the `ms-markets` documentation tree under `docs/`
(rendered by `mkdocs.yml`). Your goal is a site that reads as **one continuous,
navigable whole** — no orphans, no duplicated source-of-truth, every package
documented to the same standard, and a clear narrative path for a new reader.

Do not rewrite content that is already correct and well-placed. Fix structure,
continuity, and gaps. Make the smallest set of changes that satisfies the
invariants below, and report what you changed and what you deliberately left.

## How this relates to the `library_maintenance` skill

`library_maintenance` (`.agents/skills/library_maintenance/general_maintenance/SKILL.md`)
is a **per-change** discipline: when you touch code, update the closest doc,
example, tutorial, changelog, and validate. This prompt is the **whole-tree**
discipline: it assumes individual changes happened and checks that the docs
*as a set* are still coherent. When they conflict, this prompt wins on
structure/IA; the skill wins on per-change completeness. Keep both green.

## Target information architecture

The nav in `mkdocs.yml` must express this shape. Three packages are documented
as **peer top-level sections**, each to the same standard:

```
Home                 → what/why in one screen, links out (no deep content)
Getting Started      → install + a first example that runs
Core Concepts        → THE canonical runtime model: row objects vs *Table vs
                       DataNodes, start_engine() = attachment not schema,
                       migrations-before-runtime, MSM_AUTO_REGISTER_NAMESPACE.
                       Every other page links here instead of re-explaining it.
Tutorial             → linear narrative with "Next →" links forming a chain:
                       assets → calendars → accounts → portfolios → pricing
msm                  → core package: concepts (reference), its own ADRs/links
msm_portfolios       → TOP-LEVEL section, parity with msm (see contract below)
msm_pricing          → TOP-LEVEL section, parity with msm (see contract below)
FastAPI v1           → thin overview + one reference page per route group
Command Center       → helper/widget contracts
Architecture / ADR   → ALL ADRs, ONE tree (docs/ADR/, API ADRs under
                       docs/ADR/fast_api/v1/)
Reference            → mkdocstrings autodoc
Changelog            → snippet-include of root CHANGELOG.md (never duplicated)
```

`msm_portfolios` and `msm_pricing` are optional installable extras. Their docs
are deliberately **their own sections**, not buried under a shared "Knowledge"
heading, so the package boundary is visible to readers the way it is to the
build system.

## Invariants (must always hold after a run)

1. **No orphans.** Every `.md` under `docs/` is reachable from the `mkdocs.yml`
   nav. Nothing rendered-but-unlinked; nothing in `docs/` that isn't meant to
   publish (internal task notes, planning scratch) — those live outside `docs/`.
2. **One canonical home per fact.** A concept, route, or decision is documented
   in exactly one page; every other mention links to it. No page both links to
   a child page *and* restates the child's content.
3. **One ADR tree.** All ADRs under `docs/ADR/`. API ADRs under
   `docs/ADR/fast_api/v1/`. `docs/ADR/README.md` lists every ADR. No second
   ADR directory anywhere under `docs/`.
4. **Core Concepts is the only place** the row-vs-`*Table`-vs-DataNode model,
   `start_engine()` semantics, and `MSM_AUTO_REGISTER_NAMESPACE` are *explained*
   at length. Other pages state the one-line rule and link. (Code examples may
   still appear locally.)
5. **Three package sections at parity.** `msm`, `msm_portfolios`, `msm_pricing`
   each meet the per-package contract below.
6. **Tutorial is a path, not a dump.** It is a chain of focused chapters with
   "Next →" links; it links into reference pages rather than restating them. No
   "coming soon / this section will contain" placeholders sitting next to real
   content.
7. **Every concept page** has a `## Related Concepts` footer with working
   lateral links, so a reader is never at a dead end.
8. **Nav and entry points stay wired.** New page ⇒ added to `mkdocs.yml` and,
   if it's a new entry point, linked from `docs/index.md`.
9. **The build is strict-clean.** `mkdocs build --strict` passes.

## Per-package sub-documentation contract

Each of `msm`, `msm_portfolios`, `msm_pricing` must provide, scaled to its size:

- a **package overview** page: what it owns, what it explicitly does **not** own,
  install extra (e.g. `ms-markets[pricing]`), and a package map;
- **concept pages** for each meaningful area, each following the page template
  (below), with diagrams where a data model is involved;
- a **tutorial chapter** or at least a worked example linked from the Tutorial;
- **ADR back-links** for the decisions that set its boundaries;
- a **Related Concepts** footer that links across package boundaries
  (portfolios ↔ accounts ↔ pricing) so the three sections feel like one library.

When a package gains a new concept area, add its concept page, wire it into that
package's section in `mkdocs.yml`, and link it from the package overview.

## Concept page template

Keep concept pages to a recognizable shape. Required on every page: **Scope**
(what it owns / does not own) and **Related Concepts** (lateral links). Strongly
preferred, in this order when applicable:

1. **Scope** — what the concept owns and explicitly does not own.
2. **Tables / Relationships** — data model, with an ASCII or mermaid diagram.
3. **API** — the typed row/usage surface, with a minimal runnable snippet.
4. **Extension Rules** — where new behavior should and should not go.
5. **Related Concepts** — adjacent pages, including cross-package links.

This template is the canonical one (it used to live in `docs/knowledge/index.md`,
which was retired when the package sections were promoted to top level). Do not
reintroduce a competing template page in the user docs; keep the rule here and
the pages matching it. Required on every concept page: **Scope** and **Related
Concepts**. If a page drifts, fix the page — do not leave an aspirational
template no page follows.

## Audit procedure

Run these from the repo root and read the output before changing anything.

1. **Orphans + broken internal links** (single pass):

   ```bash
   python3 - <<'PY'
   import re, pathlib
   docs = pathlib.Path("docs")
   link_re = re.compile(r'\[[^\]]+\]\(([^)]+)\)')
   nav = pathlib.Path("mkdocs.yml").read_text()
   broken, checked = [], 0
   for md in docs.rglob("*.md"):
       for m in link_re.finditer(md.read_text(encoding="utf-8", errors="ignore")):
           href = m.group(1).split('#')[0].strip()
           if not href or href.startswith(("http://", "https://", "mailto:")):
               continue
           checked += 1
           if (href.endswith(".md") or "/" in href) and not (md.parent / href).resolve().exists():
               broken.append((str(md.relative_to(docs)), href))
   print("BROKEN LINKS:", *[f"  {s} -> {h}" for s, h in broken], sep="\n")
   print(f"\nchecked={checked} broken={len(broken)}\n")
   print("ORPHANS (not in mkdocs.yml nav):")
   for md in sorted(docs.rglob("*.md")):
       rel = str(md.relative_to(docs))
       if rel not in nav:
           print(" ", rel)
   PY
   ```

2. **Duplicated boilerplate** — the canonical runtime explanation should appear
   once (in Core Concepts). Spot drift with representative phrases:

   ```bash
   grep -rln "do not register or attach MetaTables on first use" docs/
   grep -rln "MSM_AUTO_REGISTER_NAMESPACE is" docs/
   grep -rln "start_engine" docs/ | wc -l   # expect many code uses, but only ONE prose explainer
   ```

3. **ADR tree integrity** — there must be exactly one ADR root:

   ```bash
   find docs -type d -name ADR        # expect ONLY docs/ADR
   ls docs/ADR docs/ADR/fast_api/v1 2>/dev/null
   ```

4. **Per-package coverage** — compare the three package sections for parity:

   ```bash
   for p in msm msm_portfolios msm_pricing; do
     echo "== $p =="; find docs -path "*$p*" -name "*.md" | sort
   done
   ```

5. **Strict build** — the gate:

   ```bash
   mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site
   ```

## Fix procedure (ordered)

Apply only what the audit shows is needed. Order matters:

1. **Remove dead weight first.** Move internal task/planning `.md` out of `docs/`
   (or delete if shipped). Delete vestigial redirect stubs after repointing their
   inbound links.
2. **Consolidate the ADR tree.** Move stray ADRs under `docs/ADR/`; update
   `mkdocs.yml`, `docs/ADR/README.md`, and inbound links.
3. **Extract boilerplate** into Core Concepts; replace each duplicate with a
   one-line rule + link.
4. **Realign the three package sections** to the per-package contract and the
   page template; wire every page into nav.
5. **Rebuild the Tutorial** as a linked chain; de-duplicate against reference
   pages; remove placeholders.
6. **De-duplicate the FastAPI index** down to overview + links.
7. **Re-run the full audit and `mkdocs build --strict`** until clean.

## Report format

End every run with:

- **Audit findings** — orphans, broken links, duplications, ADR/tree issues,
  package-parity gaps (with counts).
- **Changes made** — files moved/created/edited/deleted, and why.
- **Invariants status** — each of the 9 invariants: pass / fixed / still-open.
- **Deferred** — anything intentionally left, with a concrete reason.
- **Validation** — `mkdocs build --strict` result and the re-run audit output.

Keep it concise, but never silently drop a known-open item.
