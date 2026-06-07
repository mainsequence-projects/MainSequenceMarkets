from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]
else:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]

from mainsequence.client.metatables import TimeIndexMetaTable  # noqa: E402
from mainsequence.meta_tables.migrations import namespace_version_location  # noqa: E402

from examples.msm_portfolios.portfolio_equal_weights_config import (  # noqa: E402
    DYNAMIC_MIGRATION_PROVIDER,
    PORTFOLIO_EXAMPLE_RUNTIME_MODELS,
    SOURCE_PRICE_CADENCE,
    configured_equal_weight_interpolated_prices_storage,
    dynamic_provider_env,
    repair_source_cadence_metadata,
    source_cadence_from_meta_table,
    source_storage_hash_from_meta_table,
)
from examples.msm_portfolios.portfolio_equal_weights_example import (  # noqa: E402
    start_portfolio_example_runtime,
)
from examples.msm.platform.bootstrap import EXAMPLE_METATABLE_NAMESPACE  # noqa: E402
from msm_portfolios.data_nodes.prices.storage import ExternalPricesStorage  # noqa: E402


def print_step(step: int, message: str) -> None:
    print(f"{step}. {message}")


def print_detail(label: str, value: object) -> None:
    print(f"   {label}: {value}")


def prepare_equal_weight_portfolio_schema(
    *,
    check_only: bool = False,
    repair_source_cadence: bool = True,
    revision_message: str | None = None,
    run_after: bool = False,
    runtime_models: Sequence[str | type[Any]] | None = None,
) -> dict[str, Any]:
    """Prepare the configured interpolated price storage used by the example."""

    print_step(1, "Attaching the static portfolio example schema.")
    runtime = start_portfolio_example_runtime(
        models=list(runtime_models or PORTFOLIO_EXAMPLE_RUNTIME_MODELS)
    )

    source_handle = runtime.table(ExternalPricesStorage)
    if source_handle.meta_table is None:
        raise RuntimeError("ExternalPricesStorage is not attached to a TimeIndexMetaTable.")

    source_meta_table = source_handle.meta_table
    source_cadence_repaired = False
    if repair_source_cadence:
        source_meta_table, source_cadence, source_cadence_repaired = repair_source_cadence_metadata(
            source_meta_table,
            expected_cadence=SOURCE_PRICE_CADENCE,
        )
    else:
        source_cadence = source_cadence_from_meta_table(source_meta_table)

    source_storage_hash = source_storage_hash_from_meta_table(source_meta_table)
    storage_table = configured_equal_weight_interpolated_prices_storage(
        source_storage_hash=source_storage_hash,
        source_cadence=source_cadence,
    )
    provider_env = dynamic_provider_env(
        source_storage_hash=source_storage_hash,
        source_cadence=source_cadence,
    )

    print_detail("source_storage_uid", getattr(source_meta_table, "uid", None))
    print_detail("source_storage_hash", source_storage_hash)
    print_detail("source_cadence", source_cadence)
    print_detail("source_cadence_repaired", source_cadence_repaired)
    print_detail("dynamic_provider", DYNAMIC_MIGRATION_PROVIDER)
    print_detail("configured_storage_table", storage_table.__table__.name)
    print_detail("configured_storage_identifier", storage_table.metatable_identifier())

    print_step(2, "Checking the configured interpolation migration revision.")
    revision_file = _find_dynamic_revision_file(storage_table.__table__.name)
    existing = _find_time_index_meta_table(storage_table.__table__.name)
    if check_only:
        if revision_file is None:
            raise RuntimeError(
                "Configured interpolated price storage revision is missing and "
                f"--check-only was set: {storage_table.__table__.name}"
            )
        if existing is None:
            raise RuntimeError(
                "Configured interpolated price storage metadata is missing and "
                f"--check-only was set: {storage_table.__table__.name}"
            )
        print_detail("dynamic_revision_file", revision_file)
        print_detail("time_index_meta_table_uid", existing.uid)
        return {
            "source_storage_uid": getattr(source_meta_table, "uid", None),
            "source_storage_hash": source_storage_hash,
            "source_cadence": source_cadence,
            "source_cadence_repaired": source_cadence_repaired,
            "configured_storage_table": storage_table.__table__.name,
            "configured_storage_identifier": storage_table.metatable_identifier(),
            "configured_storage_uid": existing.uid,
            "created_revision": False,
        }

    created_revision = False
    if revision_file is None:
        print_step(3, "Finding or generating the dynamic Alembic revision first.")
        created_revision = True
        message = _dynamic_revision_message(
            storage_table.__table__.name,
            revision_message=revision_message,
        )
        before_revision_files = _migration_revision_files()
        _run_mainsequence(
            [
                "migrations",
                "revision",
                "--provider",
                DYNAMIC_MIGRATION_PROVIDER,
                "--autogenerate",
                "-m",
                message,
            ],
            env=provider_env,
        )
        revision_file = _find_dynamic_revision_file(storage_table.__table__.name)
        if revision_file is None:
            new_files = sorted(_migration_revision_files() - before_revision_files)
            raise RuntimeError(
                "Dynamic Alembic revision was generated, but no generated file "
                "contains the configured table CREATE TABLE operation for "
                f"{storage_table.__table__.name}. New revision files: "
                f"{[str(path) for path in new_files]}"
            )

    print_detail("dynamic_revision_file", revision_file)

    print_step(4, "Applying the dynamic migration revision.")
    _run_mainsequence(
        [
            "migrations",
            "upgrade",
            "--provider",
            DYNAMIC_MIGRATION_PROVIDER,
            "head",
        ],
        env=provider_env,
    )
    existing = _find_time_index_meta_table(storage_table.__table__.name)

    if existing is None:
        raise RuntimeError(
            "Configured interpolated price storage still does not exist after schema prep: "
            f"{storage_table.__table__.name}"
        )

    print_step(5, "Configured interpolation table is registered.")
    print_detail("time_index_meta_table_uid", existing.uid)
    print_detail("physical_table_name", getattr(existing, "physical_table_name", None))
    print_detail("storage_hash", getattr(existing, "storage_hash", None))
    print_detail("created_revision", created_revision)

    result = {
        "source_storage_uid": getattr(source_meta_table, "uid", None),
        "source_storage_hash": source_storage_hash,
        "source_cadence": source_cadence,
        "source_cadence_repaired": source_cadence_repaired,
        "configured_storage_table": storage_table.__table__.name,
        "configured_storage_identifier": storage_table.metatable_identifier(),
        "configured_storage_uid": existing.uid,
        "created_revision": created_revision,
    }

    if run_after:
        print_step(6, "Running the portfolio workflow after schema preparation.")
        from examples.msm_portfolios.portfolio_equal_weights_example import (
            build_equal_weight_portfolio,
        )

        result["portfolio_result"] = build_equal_weight_portfolio(runtime_models=runtime_models)

    return result


def _find_time_index_meta_table(table_name: str) -> Any | None:
    matches = TimeIndexMetaTable.filter_by_body(
        physical_table_name__in=[table_name],
        limit=1,
        offset=0,
    )
    return matches[0] if matches else None


def _dynamic_revision_message(
    table_name: str,
    *,
    revision_message: str | None,
) -> str:
    if revision_message not in (None, ""):
        return str(revision_message)
    table_suffix = table_name.rsplit("_", 1)[-1]
    return f"portfolio_equal_weights_dynamic_interpolated_prices_{table_suffix}"


def _find_dynamic_revision_file(table_name: str) -> Path | None:
    for path in sorted(_migration_revision_files()):
        content = path.read_text(encoding="utf-8")
        if table_name in content and "op.create_table" in content:
            return path
    return None


def _migration_revision_files() -> set[Path]:
    versions_root = _active_version_directory()
    return {path for path in versions_root.glob("**/*.py") if path.name != "__init__.py"}


def _active_version_directory() -> Path:
    version_location = namespace_version_location(EXAMPLE_METATABLE_NAMESPACE)
    package_name, separator, resource_path = version_location.partition(":")
    if not separator or not package_name or not resource_path:
        raise RuntimeError(
            f"Dynamic migration provider returned an invalid version location: {version_location!r}"
        )

    traversable = resources.files(package_name)
    for part in resource_path.strip("/").split("/"):
        if part:
            traversable = traversable.joinpath(part)
    return Path(str(traversable))


def _run_mainsequence(
    args: list[str],
    *,
    env: dict[str, str],
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    command_env = _command_env(env)
    command = [sys.executable, "-m", "mainsequence", *args]
    print_detail("command", " ".join(command))
    result = subprocess.run(
        command,
        cwd=_PROJECT_ROOT,
        env=command_env,
        check=False,
        text=True,
    )
    if result.returncode != 0 and not allow_failure:
        raise subprocess.CalledProcessError(result.returncode, command)
    return result


def _command_env(extra_env: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(extra_env)
    paths = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify that the configured dynamic table exists.",
    )
    parser.add_argument(
        "--no-repair-source-cadence",
        action="store_true",
        help=(
            "Fail if the registered source price TimeIndexMetaTable is missing "
            "cadence metadata instead of patching it to the model-declared cadence."
        ),
    )
    parser.add_argument(
        "--revision-message",
        help="Custom Alembic revision message when a new dynamic revision is needed.",
    )
    parser.add_argument(
        "--run-after",
        action="store_true",
        help="Run the equal-weight portfolio workflow after the schema is prepared.",
    )
    args = parser.parse_args()
    prepare_equal_weight_portfolio_schema(
        check_only=args.check_only,
        repair_source_cadence=not args.no_repair_source_cadence,
        revision_message=args.revision_message,
        run_after=args.run_after,
    )


if __name__ == "__main__":
    main()
