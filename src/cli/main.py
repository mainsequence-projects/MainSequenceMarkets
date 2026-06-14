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
BUNDLED_MSM_SKILLS_PATH = SOURCE_MSM_SKILLS_PATH
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
    parser.print_help()
    return 1


def copy_msm_skills_command(
    *,
    path: Path,
    dry_run: bool = False,
    emit_json: bool = False,
) -> int:
    source_root = bundled_msm_skills_root()
    if not source_root.exists() or not source_root.is_dir():
        raise SystemExit(f"Packaged ms-markets skill bundle is missing: {source_root}")

    project_dir = path.expanduser().resolve(strict=False)
    destination_root = project_dir / ".agents" / "skills" / MSM_SKILL_NAMESPACE
    source_label = _source_root_label(source_root)
    try:
        result = copy_scaffold_skills(
            project_dir=project_dir,
            library_name="ms-markets",
            namespace=MSM_SKILL_NAMESPACE,
            skills_path=source_root,
            pinned_version=_ms_markets_version(),
            command=MSM_SKILL_COPY_COMMAND,
            dry_run=dry_run,
            project_guard=_copy_msm_skills_block_reason,
        )
    except ScaffoldSkillCopyBlocked as exc:
        payload = {
            "blocked": True,
            "destination_root": str(destination_root),
            "dry_run": dry_run,
            "project": str(project_dir),
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
        "project": str(project_dir),
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

    try:
        dist = distribution("ms-markets")
    except PackageNotFoundError as exc:
        raise RuntimeError("ms-markets package metadata is unavailable.") from exc
    return Path(dist.locate_file("/".join(BUNDLED_MSM_SKILLS_PATH)))


def source_tree_msm_skills_root() -> Path:
    return Path(__file__).resolve().parents[2].joinpath(*SOURCE_MSM_SKILLS_PATH)


def _ms_markets_source_checkout_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _copy_msm_skills_block_reason(
    project_dir: Path,
) -> str | None:
    source_checkout_root = _ms_markets_source_checkout_root()
    if _same_or_inside_path(project_dir, source_checkout_root) or _is_ms_markets_source_checkout(
        project_dir
    ):
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
