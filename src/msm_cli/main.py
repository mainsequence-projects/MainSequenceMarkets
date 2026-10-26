from __future__ import annotations

import argparse
import json
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, distribution
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
    if args.command == "rename-preflight" and args.preflight:
        return rename_preflight_command(args)
    if args.command == "series" and args.series:
        return series_command(args)
    parser.print_help()
    return 1


def rename_preflight_command(args: argparse.Namespace) -> int:
    """Run one ``msm rename-preflight`` check (ADR 0048)."""

    from msm_cli import rename_preflight

    if args.preflight == "scan":
        findings = rename_preflight.scan(Path(path) for path in args.paths)
        rows = rename_preflight.as_dicts(findings)
        if args.emit_json:
            print(json.dumps(rows, indent=2))
        else:
            _print_table(
                "Pre-3.0 names to replace",
                ["File", "Line", "Kind", "Pre-3.0", "Use"],
                [[r["path"], r["line"], r["kind"], r["old"], r["new"]] for r in rows],
            )
        return 1 if findings else 0
    if args.preflight == "rotation":
        report = rename_preflight.rotation(rename_preflight.load_objects(args.objects))
        if args.emit_json:
            print(json.dumps(report, indent=2))
        else:
            _print_table(
                "Updater identities under 3.0",
                ["Updater", "Rotated", "update_hash", "Pre-3.0 update_hash"],
                [
                    [r["updater"], r["rotated"], r["update_hash"], r["pre_3_0_update_hash"]]
                    for r in report
                ],
            )
        return 0
    report = rename_preflight.account_uids(limit=args.limit)
    if args.emit_json:
        print(json.dumps(report, indent=2))
    else:
        _print_table(
            "Stored account UIDs",
            ["Table", "Column", "Classification", "Count", "Examples"],
            [
                [
                    r["table"],
                    r["column"],
                    r["classification"],
                    r["count"],
                    ", ".join(r["examples"]),
                ]
                for r in report
            ],
        )
    return 0 if all(r["classification"] == "TimeIndexMetaTable" for r in report) else 1


def series_command(args: argparse.Namespace) -> int:
    """Run ``msm series move|rollback`` over the moves a provider callable returns (ADR 0047)."""

    from msm.storage_copies import run_series_moves
    from msm_cli.rename_preflight import load_objects

    report = run_series_moves(
        load_objects(args.moves),
        rollback=args.series == "rollback",
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
    try:
        result = copy_scaffold_skills(
            code_repository_dir=code_repository_dir,
            library_name="ms-markets",
            namespace=MSM_SKILL_NAMESPACE,
            skills_path=source_root,
            pinned_version=_ms_markets_version(),
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

    preflight_parser = subparsers.add_parser(
        "rename-preflight",
        help="Find what moving to ms-markets 3.0 changes in a host project (ADR 0048).",
    )
    preflight = preflight_parser.add_subparsers(dest="preflight")
    scan_parser = preflight.add_parser(
        "scan",
        help="List pre-3.0 import paths, class names and UID field names; exits 1 if any.",
    )
    scan_parser.add_argument("paths", nargs="+", help="Files or directories to scan.")
    rotation_parser = preflight.add_parser(
        "rotation",
        help="Show which updaters got a new update_hash and their pre-3.0 hash.",
    )
    rotation_parser.add_argument(
        "objects",
        help="module:callable returning the updaters, signals or portfolio configurations.",
    )
    uids_parser = preflight.add_parser(
        "account-uids",
        help="Classify stored account UIDs; exits 1 unless all are storage tables.",
    )
    uids_parser.add_argument(
        "--limit", type=int, default=10_000, help="Rows to read from each table."
    )
    for sub in (scan_parser, rotation_parser, uids_parser):
        sub.add_argument(
            "--json", dest="emit_json", action="store_true", help="Emit machine-readable JSON."
        )

    series_parser = subparsers.add_parser(
        "series",
        help="Move time series into a provider's instances, or roll them back (ADR 0047).",
    )
    series = series_parser.add_subparsers(dest="series")
    for name, help_text in (
        ("move", "Copy core rows into the instances, then record them in Markets."),
        ("rollback", "Copy the instances' new rows back, then remove the Markets records."),
    ):
        sub = series.add_parser(name, help=help_text)
        sub.add_argument(
            "moves",
            help=(
                "module:callable returning TableSeriesMove, PortfolioSeriesMove or "
                "SignalSeriesMove objects, after attaching the provider's runtime."
            ),
        )
        sub.add_argument(
            "--execute",
            action="store_true",
            help="Copy and update Markets; without it only count the rows.",
        )
        sub.add_argument(
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


def _ms_markets_version() -> str:
    try:
        return distribution("ms-markets").version
    except PackageNotFoundError:
        pyproject = _ms_markets_source_checkout_root() / "pyproject.toml"
        if not pyproject.is_file():
            raise RuntimeError("ms-markets package metadata is unavailable.")
        project_config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = project_config.get("project", {}).get("version")
        if not isinstance(version, str) or not version.strip():
            raise RuntimeError("ms-markets package version is unavailable.")
        return version


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
