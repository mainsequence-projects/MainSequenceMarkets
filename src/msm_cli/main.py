from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mainsequence.scaffold_skills import ScaffoldSkillCopyBlocked, copy_scaffold_skills

SOURCE_MSM_SKILLS_PATH = (".agents", "skills", "ms_markets")
# The wheel ships the skills inside this package, never as a top-level `.agents`.
BUNDLED_MSM_SKILLS_PATH = ("msm_cli", "_skills", "ms_markets")
MSM_SKILL_NAMESPACE = "ms_markets"
MSM_SKILL_COPY_COMMAND = "msm copy-msm-skills"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "copy-msm-skills":
        return copy_msm_skills_command(
            path=Path(args.path),
            dry_run=args.dry_run,
            emit_json=args.emit_json,
        )
    if args.command == "series" and args.series == "publish":
        return series_publish_command(args)
    if args.command == "registry" and args.registry == "assign-manager":
        return assign_manager_command(args)
    if args.command == "series" and args.series:
        return series_command(args)
    parser.print_help()
    return 1


def series_publish_command(args: argparse.Namespace) -> int:
    """Run ``msm series publish`` over what an operator callable returns (ADR 0060, decision 9)."""

    import importlib

    from msm.storage_copies import run_series_publishes

    module_name, _, attribute = args.publishes.partition(":")
    if not module_name or not attribute:
        raise SystemExit("Pass the publishes as module:callable.")
    produced = getattr(importlib.import_module(module_name), attribute)()
    report = run_series_publishes(
        list(produced) if isinstance(produced, (list, tuple, set, frozenset)) else [produced],
        dry_run=not args.execute,
    )
    if args.emit_json:
        print(json.dumps(report.summary(), indent=2, default=str))
        return 0 if report.succeeded else 1
    _print_table(
        f"Publish of series history{' (dry run: nothing written)' if report.dry_run else ''}",
        ["Publish", "Key", "Source rows", "Written", "Skipped", "Markets rows", "Verified", "Error"],
        [
            [
                label,
                key.key,
                key.source_rows,
                key.written,
                key.skipped,
                key.markets_rows,
                key.verified,
                key.error,
            ]
            for label, key in report.results
        ],
    )
    return 0 if report.succeeded else 1


def assign_manager_command(args: argparse.Namespace) -> int:
    """Run ``msm registry assign-manager`` (ADR 0060, decision 9)."""

    import importlib

    from msm.api.managers import assign_managers

    if args.attach:
        module_name, _, attribute = args.attach.partition(":")
        if not module_name or not attribute:
            raise SystemExit("Pass --attach as module:callable.")
        getattr(importlib.import_module(module_name), attribute)()
    try:
        assignments = assign_managers(
            args.manager,
            keys={"portfolio": args.portfolio or (), "signal": args.signal or ()},
            unmanaged=args.unmanaged,
            dry_run=not args.execute,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.emit_json:
        print(json.dumps([assignment.__dict__ for assignment in assignments], indent=2))
    else:
        _print_table(
            f"Manager assignment{' (dry run: nothing changed)' if not args.execute else ''}",
            ["Kind", "Key", "UID", "Previous", "Manager", "Assigned", "Detail"],
            [
                [a.kind, a.key, a.uid, a.previous, a.managed_by, a.assigned, a.detail]
                for a in assignments
            ],
        )
    return 0 if all(a.uid is not None for a in assignments) else 1


def series_command(args: argparse.Namespace) -> int:
    """Run ``msm series move|rollback`` over the moves an operator callable returns."""

    import importlib
    import inspect

    from msm.storage_copies import run_series_moves

    rollback = args.series == "rollback"
    module_name, _, attribute = args.moves.partition(":")
    if not module_name or not attribute:
        raise SystemExit("Pass the moves as module:callable.")
    produce = getattr(importlib.import_module(module_name), attribute)
    # A callable that takes ``rollback`` builds the moves for that direction.
    accepts_rollback = "rollback" in inspect.signature(produce).parameters
    produced = produce(rollback=rollback) if accepts_rollback else produce()
    report = run_series_moves(
        list(produced) if isinstance(produced, (list, tuple, set, frozenset)) else [produced],
        rollback=rollback,
        dry_run=not args.execute,
    )
    if args.emit_json:
        print(json.dumps(report.summary(), indent=2, default=str))
        return 0 if report.succeeded else 1
    rows: list[list[Any]] = []
    for result in report.results:
        if not result.copies:
            rows.append([result.kind, result.label, result.status, result.detail, "", "", ""])
        for copy in result.copies:
            rows.append(
                [
                    result.kind,
                    result.label,
                    result.status,
                    f"{copy.source_table} -> {copy.target_table}",
                    sum(key.source_rows for key in copy.keys),
                    sum(key.target_rows for key in copy.keys),
                    sum(key.missing_rows for key in copy.keys),
                ]
            )
    action = "Rollback" if report.rollback else "Move"
    _print_table(
        f"{action} of time series{' (dry run: nothing written)' if report.dry_run else ''}",
        ["Kind", "Move", "Status", "Copy", "Source rows", "Target rows", "Missing"],
        rows,
    )
    return 0 if report.succeeded else 1


def copy_msm_skills_command(
    *,
    path: Path,
    dry_run: bool = False,
    emit_json: bool = False,
) -> int:
    source_root = bundled_msm_skills_root()
    if not source_root.exists() or not source_root.is_dir():
        raise SystemExit(f"Packaged ms-markets skill bundle is missing: {source_root}")

    code_repository_dir = path.expanduser().resolve(strict=False)
    destination_root = code_repository_dir / ".agents" / "skills" / MSM_SKILL_NAMESPACE
    source_label = _source_root_label(source_root)
    from msm.distribution import package_version

    try:
        result = copy_scaffold_skills(
            code_repository_dir=code_repository_dir,
            library_name="ms-markets",
            namespace=MSM_SKILL_NAMESPACE,
            skills_path=source_root,
            pinned_version=package_version(),
            command=MSM_SKILL_COPY_COMMAND,
            dry_run=dry_run,
            code_repository_guard=_copy_msm_skills_block_reason,
        )
    except ScaffoldSkillCopyBlocked as exc:
        payload = {
            "blocked": True,
            "destination_root": str(destination_root),
            "dry_run": dry_run,
            "code_repository": str(code_repository_dir),
            "reason": str(exc),
            "source": source_label,
            "updated": [],
            "updated_count": 0,
        }
        if emit_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(str(exc), file=sys.stderr)
        return 2

    copied = [
        {
            "name": item.name,
            "source": f"{source_label}/{item.name}",
            "destination": str(item.destination),
        }
        for item in result.copied
    ]
    payload = {
        "code_repository": str(code_repository_dir),
        "source": source_label,
        "destination_root": str(result.destination_root),
        "library_name": result.library_name,
        "namespace": result.namespace,
        "pinned_version": result.pinned_version,
        "sentinel_path": str(result.sentinel_path),
        "dry_run": dry_run,
        "updated_count": len(copied),
        "updated": copied,
    }

    if emit_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    action = "Would update" if dry_run else "Updated"
    print(f"{action} .agents/skills/ms_markets from packaged ms-markets skills.")
    _print_table(
        "MS Markets Skills",
        ["Skill Folder", "Destination"],
        [[item["name"], item["destination"]] for item in copied],
    )
    return 0


def bundled_msm_skills_root() -> Path:
    source_root = source_tree_msm_skills_root()
    if source_root.is_dir():
        return source_root
    bundled_root = Path(__file__).resolve().parent.joinpath(*BUNDLED_MSM_SKILLS_PATH[1:])
    if not bundled_root.is_dir():
        raise RuntimeError("The installed ms-markets skill bundle is missing. Reinstall ms-markets.")
    return bundled_root


def source_tree_msm_skills_root() -> Path:
    return Path(__file__).resolve().parents[2].joinpath(*SOURCE_MSM_SKILLS_PATH)


def _ms_markets_source_checkout_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _copy_msm_skills_block_reason(
    code_repository_dir: Path,
) -> str | None:
    source_checkout_root = _ms_markets_source_checkout_root()
    if _same_or_inside_path(
        code_repository_dir, source_checkout_root
    ) or _is_ms_markets_source_checkout(code_repository_dir):
        return (
            "Blocked: msm copy-msm-skills cannot run inside the ms-markets source "
            "checkout. Use this command only from a separate host project."
        )

    return None


def _is_ms_markets_source_checkout(path: Path) -> bool:
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        project_config = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        'name = "ms-markets"' in project_config
        and (path / "src" / "msm").is_dir()
        and (path / ".agents" / "skills" / "ms_markets").is_dir()
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="msm",
        description="Command-line helpers for the ms-markets package.",
    )
    subparsers = parser.add_subparsers(dest="command")

    copy_parser = subparsers.add_parser(
        "copy-msm-skills",
        help="Copy packaged ms-markets agent skills into a host CodeRepository.",
    )
    copy_parser.add_argument(
        "--path",
        default=".",
        help="Host CodeRepository directory. Defaults to the current directory.",
    )
    copy_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without writing files.",
    )
    copy_parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )

    series_parser = subparsers.add_parser(
        "series",
        help=(
            "Publish an application's series history to Markets (ADR 0060), or copy time "
            "series between two tables with the operator's own access."
        ),
    )
    series = series_parser.add_subparsers(dest="series")
    publish_parser = series.add_parser(
        "publish",
        help=(
            "Read an application's own table with the operator's access, publish its rows to "
            "the Markets series key by key, and compare the bounds. The source is unchanged."
        ),
    )
    publish_parser.add_argument(
        "publishes",
        help=(
            "module:callable returning the publishes to run, after attaching the operator's "
            "runtime. Each is an object of the package that defines the series, with "
            "run(dry_run=...)."
        ),
    )
    publish_parser.add_argument(
        "--execute", action="store_true", help="Publish; without it only read and compare."
    )
    publish_parser.add_argument(
        "--json", dest="emit_json", action="store_true", help="Emit machine-readable JSON."
    )
    for name, help_text in (
        ("move", "Copy the rows of some keys from one table into another."),
        ("rollback", "Copy the rows the target gained back into the source."),
    ):
        sub = series.add_parser(name, help=help_text)
        sub.add_argument(
            "moves",
            help=(
                "module:callable returning TableSeriesMove objects, after attaching "
                "the operator's runtime; it receives rollback= when it accepts that "
                "argument."
            ),
        )
        sub.add_argument(
            "--execute",
            action="store_true",
            help="Copy; without it only count the rows.",
        )
        sub.add_argument(
            "--json", dest="emit_json", action="store_true", help="Emit machine-readable JSON."
        )
    registry_parser = subparsers.add_parser(
        "registry", help="Operate on Markets registry rows (ADR 0060)."
    )
    registry = registry_parser.add_subparsers(dest="registry")
    assign = registry.add_parser(
        "assign-manager",
        help=(
            "Set managed_by on portfolios and signals, for example rows created before it "
            "existed. Through the Markets API only an Organization admin may."
        ),
    )
    assign.add_argument(
        "--manager", required=True, help="The principal: branch:<uid> or user:<uid>."
    )
    assign.add_argument(
        "--portfolio", action="append", help="Portfolio unique_identifier; repeatable."
    )
    assign.add_argument("--signal", action="append", help="SignalMetadata signal_uid; repeatable.")
    assign.add_argument(
        "--attach",
        help=(
            "module:callable run first: it attaches the operator's runtime and imports the "
            "packages whose rows are assigned. Signals need the package that serves them."
        ),
    )
    assign.add_argument(
        "--unmanaged", action="store_true", help="Also every portfolio and signal without a manager."
    )
    assign.add_argument(
        "--execute", action="store_true", help="Assign; without it only list the rows."
    )
    assign.add_argument(
        "--json", dest="emit_json", action="store_true", help="Emit machine-readable JSON."
    )
    return parser


def _source_root_label(source_root: Path) -> str:
    if source_root.resolve() == source_tree_msm_skills_root().resolve():
        return "/".join(SOURCE_MSM_SKILLS_PATH)
    return "/".join(BUNDLED_MSM_SKILLS_PATH)


def _same_or_inside_path(path: Path, possible_parent: Path) -> bool:
    resolved_path = path.expanduser().resolve(strict=False)
    resolved_parent = possible_parent.expanduser().resolve(strict=False)
    return resolved_path == resolved_parent or resolved_path.is_relative_to(resolved_parent)


def _print_table(title: str, headers: list[str], rows: list[list[Any]]) -> None:
    print(title)
    if not rows:
        print("  (no rows)")
        return

    widths = [
        max(len(str(value)) for value in [header, *(row[index] for row in rows)])
        for index, header in enumerate(headers)
    ]
    header_line = "  " + "  ".join(
        str(header).ljust(widths[index]) for index, header in enumerate(headers)
    )
    separator = "  " + "  ".join("-" * width for width in widths)
    print(header_line)
    print(separator)
    for row in rows:
        print("  " + "  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


if __name__ == "__main__":
    sys.exit(main())
