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
    if args.command == "catalog":
        if args.catalog_command == "rotate":
            return catalog_rotate_command(
                model=args.model,
                emit_json=args.emit_json,
            )
        parser.print_help()
        return 1
    if args.command == "migrations":
        if args.migrations_command == "current":
            return migrations_current_command(
                data_source_uid=args.data_source_uid,
                namespace=args.namespace,
                emit_json=args.emit_json,
            )
        if args.migrations_command == "sync":
            return migrations_sync_command(
                data_source_uid=args.data_source_uid,
                namespace=args.namespace,
                emit_json=args.emit_json,
            )
        if args.migrations_command == "upgrade":
            return migrations_upgrade_command(
                data_source_uid=args.data_source_uid,
                namespace=args.namespace,
                dry_run=args.dry_run,
                emit_json=args.emit_json,
            )
        if args.migrations_command == "validate":
            return migrations_validate_command(
                data_source_uid=args.data_source_uid,
                namespace=args.namespace,
                emit_json=args.emit_json,
            )
        parser.print_help()
        return 1

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


def catalog_rotate_command(
    *,
    model: str,
    emit_json: bool = False,
) -> int:
    from msm.maintenance.catalog import rotate_catalogue

    result = rotate_catalogue(model)
    payload = result.to_payload()
    if emit_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Rotated markets MetaTable catalog row for {payload['identifier']}.")
    _print_table(
        "Catalog Rotation",
        ["Field", "Value"],
        [
            ["Model", payload["model_name"]],
            ["Identifier", payload["identifier"]],
            ["MetaTable UID", payload["meta_table_uid"]],
            ["Old Contract Hash", payload["old_contract_hash"]],
            ["New Contract Hash", payload["new_contract_hash"]],
            ["Changed", payload["changed"]],
        ],
    )
    return 0


def migrations_current_command(
    *,
    data_source_uid: str | None = None,
    namespace: str | None = None,
    emit_json: bool = False,
) -> int:
    from msm.maintenance.migrations import MigrationStateError, MigrationSupportError
    from msm.maintenance.migrations import current_migrations

    try:
        result = current_migrations(
            data_source_uid=data_source_uid,
            namespace=namespace,
        )
    except (MigrationStateError, MigrationSupportError) as exc:
        return _emit_command_error(exc)
    return _emit_migration_result("current", result.to_payload(), emit_json=emit_json)


def migrations_sync_command(
    *,
    data_source_uid: str,
    namespace: str | None = None,
    emit_json: bool = False,
) -> int:
    from msm.maintenance.migrations import MigrationStateError, MigrationSupportError
    from msm.maintenance.migrations import sync_migrations

    try:
        result = sync_migrations(
            data_source_uid=data_source_uid,
            namespace=namespace,
        )
    except (MigrationStateError, MigrationSupportError) as exc:
        return _emit_command_error(exc)
    return _emit_migration_result("sync", result.to_payload(), emit_json=emit_json)


def migrations_upgrade_command(
    *,
    data_source_uid: str,
    namespace: str | None = None,
    dry_run: bool = False,
    emit_json: bool = False,
) -> int:
    from msm.maintenance.migrations import MigrationStateError, MigrationSupportError
    from msm.maintenance.migrations import upgrade_migrations

    try:
        result = upgrade_migrations(
            data_source_uid=data_source_uid,
            namespace=namespace,
            dry_run=dry_run,
        )
    except (MigrationStateError, MigrationSupportError) as exc:
        return _emit_command_error(exc)
    return _emit_migration_result("upgrade", result.to_payload(), emit_json=emit_json)


def migrations_validate_command(
    *,
    data_source_uid: str | None = None,
    namespace: str | None = None,
    emit_json: bool = False,
) -> int:
    from msm.maintenance.migrations import MigrationStateError, MigrationSupportError
    from msm.maintenance.migrations import validate_migrations

    try:
        result = validate_migrations(
            data_source_uid=data_source_uid,
            namespace=namespace,
        )
    except (MigrationStateError, MigrationSupportError) as exc:
        return _emit_command_error(exc)
    return _emit_migration_result("validate", result.to_payload(), emit_json=emit_json)


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
    catalog_parser = subparsers.add_parser(
        "catalog",
        help="Maintenance commands for the markets MetaTable catalog.",
    )
    catalog_subparsers = catalog_parser.add_subparsers(dest="catalog_command")
    rotate_parser = catalog_subparsers.add_parser(
        "rotate",
        help="Replace one catalog row using the model's registered MetaTable.",
    )
    rotate_parser.add_argument(
        "model",
        help="Markets model key, for example Account, AccountTable, or a full identifier.",
    )
    rotate_parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    migrations_parser = subparsers.add_parser(
        "migrations",
        help="Admin commands for SDK-managed markets MetaTable migrations.",
    )
    migrations_subparsers = migrations_parser.add_subparsers(dest="migrations_command")

    current_parser = migrations_subparsers.add_parser(
        "current",
        help="Show expected package revisions, SDK status, and catalog finalization.",
    )
    _add_migration_common_args(current_parser, data_source_required=True)

    sync_parser = migrations_subparsers.add_parser(
        "sync",
        help="Sync packaged migration rows into the SDK MigrationMetaTable.",
    )
    _add_migration_common_args(sync_parser, data_source_required=True)

    upgrade_parser = migrations_subparsers.add_parser(
        "upgrade",
        help="Sync and apply packaged migration rows, then finalize the catalog.",
    )
    _add_migration_common_args(upgrade_parser, data_source_required=True)
    upgrade_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and validate apply requests without committing DDL or catalog rows.",
    )

    validate_parser = migrations_subparsers.add_parser(
        "validate",
        help="Fail unless SDK migration status and the markets catalog are current.",
    )
    _add_migration_common_args(validate_parser, data_source_required=True)
    return parser


def _add_migration_common_args(
    parser: argparse.ArgumentParser,
    *,
    data_source_required: bool,
) -> None:
    parser.add_argument(
        "--data-source-uid",
        required=data_source_required,
        help="DynamicTable data source UID for the migration stream.",
    )
    parser.add_argument(
        "--namespace",
        help="Markets namespace. Defaults to the package/runtime default.",
    )
    parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )


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
        print("  (no skills found)")
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


def _emit_migration_result(command: str, payload: dict[str, Any], *, emit_json: bool) -> int:
    if emit_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"msm migrations {command}: {'current' if payload.get('ok') else 'not current'}")
    _print_table(
        "Migration Status",
        ["Field", "Value"],
        [
            ["Namespace", payload.get("migration_namespace")],
            ["Registry UID", payload.get("migration_registry_uid")],
            ["Expected Revisions", ", ".join(payload.get("expected_revisions") or [])],
            ["Synced", len(payload.get("synced") or [])],
            ["Applied", len(payload.get("applied") or [])],
            ["Skipped", ", ".join(payload.get("skipped") or [])],
        ],
    )
    catalog_status = payload.get("catalog_status") or []
    _print_table(
        "Catalog Status",
        ["Identifier", "Status"],
        [
            [str(item.get("identifier")), str(item.get("status"))]
            for item in catalog_status
            if isinstance(item, dict)
        ],
    )
    return 0


def _emit_command_error(exc: Exception) -> int:
    print(str(exc), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
