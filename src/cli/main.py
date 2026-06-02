from __future__ import annotations

import argparse
import json
import shutil
import sys
from importlib import resources
from importlib.abc import Traversable
from pathlib import Path
from typing import Any

MSM_SKILLS_RESOURCE = (".agents", "ms_markets")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "copy-msm-skills":
        return copy_msm_skills_command(
            path=Path(args.path),
            dry_run=args.dry_run,
            emit_json=args.emit_json,
        )
    parser.print_help()
    return 1


def copy_msm_skills_command(
    *,
    path: Path,
    dry_run: bool = False,
    emit_json: bool = False,
) -> int:
    source_root = bundled_msm_skills_root()
    if not _traversable_exists(source_root) or not source_root.is_dir():
        raise SystemExit(f"Packaged ms-markets skill bundle is missing: {source_root}")

    project_dir = path.expanduser().resolve()
    destination_root = project_dir / ".agents" / "skills" / "ms_markets"
    skill_sources = _iter_skill_roots(source_root)

    copied = [
        {
            "name": source.name,
            "source": "/".join(MSM_SKILLS_RESOURCE + (source.name,)),
            "destination": str(destination_root / source.name),
        }
        for source in skill_sources
    ]
    payload = {
        "project": str(project_dir),
        "source": "/".join(MSM_SKILLS_RESOURCE),
        "destination_root": str(destination_root),
        "dry_run": dry_run,
        "updated_count": len(copied),
        "updated": copied,
    }

    if not dry_run:
        for source in skill_sources:
            destination = destination_root / source.name
            _copy_traversable_tree(source, destination)

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


def bundled_msm_skills_root() -> Traversable:
    root = resources.files("msm")
    for part in MSM_SKILLS_RESOURCE:
        root = root.joinpath(part)
    return root


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="msm",
        description="Command-line helpers for the ms-markets package.",
    )
    subparsers = parser.add_subparsers(dest="command")

    copy_parser = subparsers.add_parser(
        "copy-msm-skills",
        help="Copy packaged ms-markets agent skills into a host project.",
    )
    copy_parser.add_argument(
        "--path",
        default=".",
        help="Host project directory. Defaults to the current directory.",
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
    return parser


def _iter_skill_roots(source_root: Traversable) -> list[Traversable]:
    return [
        item
        for item in sorted(source_root.iterdir(), key=lambda child: child.name)
        if item.is_dir() and not item.name.startswith(".") and not item.name.startswith("__")
    ]


def _copy_traversable_tree(source: Traversable, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    for child in source.iterdir():
        child_destination = destination / child.name
        if child.is_dir():
            _copy_traversable_tree(child, child_destination)
            continue
        if child.is_file():
            child_destination.parent.mkdir(parents=True, exist_ok=True)
            child_destination.write_bytes(child.read_bytes())


def _traversable_exists(item: Traversable) -> bool:
    try:
        return item.exists()
    except FileNotFoundError:
        return False


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
