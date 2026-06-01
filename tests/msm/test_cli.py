from __future__ import annotations

import importlib
import json
import pathlib
from types import SimpleNamespace

import pytest

from cli.main import bundled_msm_skills_root, main

cli_main = importlib.import_module("cli.main")


def _bundled_bundle_names() -> list[str]:
    return sorted(
        item.name
        for item in bundled_msm_skills_root().iterdir()
        if item.is_dir() and not item.name.startswith(".") and not item.name.startswith("__")
    )


def _bundled_skill_paths() -> list[str]:
    paths: list[str] = []

    def walk(prefix: tuple[str, ...], root) -> None:
        for item in root.iterdir():
            if item.name.startswith(".") or item.name.startswith("__"):
                continue
            if not item.is_dir():
                continue

            path = (*prefix, item.name)
            if item.joinpath("SKILL.md").is_file():
                paths.append("/".join(path))
            walk(path, item)

    walk((), bundled_msm_skills_root())
    return sorted(paths)


def test_import_msm_does_not_copy_skills(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    import msm  # noqa: F401

    assert not (tmp_path / ".agents").exists()


def test_msm_cli_module_is_not_runtime_surface() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("msm.cli")


def test_copy_msm_skills_dry_run_writes_nothing(tmp_path, capsys) -> None:
    exit_code = main(["copy-msm-skills", "--path", str(tmp_path), "--dry-run", "--json"])

    assert exit_code == 0
    assert not (tmp_path / ".agents").exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["destination_root"] == str(tmp_path / ".agents" / "skills" / "ms_markets")
    assert sorted(item["name"] for item in payload["updated"]) == _bundled_bundle_names()


def test_copy_msm_skills_copies_only_ms_markets_namespace(tmp_path) -> None:
    mainsequence_skill = tmp_path / ".agents" / "skills" / "mainsequence" / "project_builder"
    mainsequence_skill.mkdir(parents=True)
    sentinel = mainsequence_skill / "SKILL.md"
    sentinel.write_text("keep me", encoding="utf-8")

    stale_skill = tmp_path / ".agents" / "skills" / "ms_markets" / _bundled_bundle_names()[0]
    stale_skill.mkdir(parents=True)
    stale_file = stale_skill / "stale.txt"
    stale_file.write_text("remove me", encoding="utf-8")

    exit_code = main(["copy-msm-skills", "--path", str(tmp_path)])

    assert exit_code == 0
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert not stale_file.exists()
    assert not (tmp_path / ".agents" / "ms_markets").exists()
    for skill_path in _bundled_skill_paths():
        skill_file = (
            tmp_path
            / ".agents"
            / "skills"
            / "ms_markets"
            / pathlib.Path(*skill_path.split("/"))
            / "SKILL.md"
        )
        assert skill_file.exists()


def test_catalog_rotate_command_routes_model_to_catalogue_rotation(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_catalog_rotate_command(*, model: str, emit_json: bool = False) -> int:
        calls.append({"model": model, "emit_json": emit_json})
        return 0

    monkeypatch.setattr(cli_main, "catalog_rotate_command", fake_catalog_rotate_command)

    exit_code = main(["catalog", "rotate", "Account", "--json"])

    assert exit_code == 0
    assert calls == [{"model": "Account", "emit_json": True}]
    assert capsys.readouterr().out == ""


def test_catalog_rotate_command_emits_json(monkeypatch, capsys) -> None:
    import msm.maintenance.catalog as catalog

    result = SimpleNamespace(
        to_payload=lambda: {
            "identifier": "Account",
            "model_name": "AccountTable",
            "meta_table_uid": "account-meta-table-uid",
            "old_contract_hash": "old",
            "new_contract_hash": "new",
            "changed": True,
            "row": {"identifier": "Account"},
        }
    )
    calls: list[str] = []

    def fake_rotate_catalogue(model: str):
        calls.append(model)
        return result

    monkeypatch.setattr(catalog, "rotate_catalogue", fake_rotate_catalogue)

    exit_code = cli_main.catalog_rotate_command(model="Account", emit_json=True)

    assert exit_code == 0
    assert calls == ["Account"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["identifier"] == "Account"
    assert payload["meta_table_uid"] == "account-meta-table-uid"


def test_migrations_current_command_routes_to_migration_command(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_migrations_current_command(
        *,
        data_source_uid: str | None = None,
        namespace: str | None = None,
        emit_json: bool = False,
    ) -> int:
        calls.append(
            {
                "data_source_uid": data_source_uid,
                "namespace": namespace,
                "emit_json": emit_json,
            }
        )
        return 0

    monkeypatch.setattr(cli_main, "migrations_current_command", fake_migrations_current_command)

    exit_code = main(
        [
            "migrations",
            "current",
            "--data-source-uid",
            "data-source-uid",
            "--namespace",
            "mainsequence.examples",
            "--json",
        ]
    )

    assert exit_code == 0
    assert calls == [
        {
            "data_source_uid": "data-source-uid",
            "namespace": "mainsequence.examples",
            "emit_json": True,
        }
    ]
    assert capsys.readouterr().out == ""


def test_migrations_upgrade_requires_data_source_uid(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["migrations", "upgrade"])
    assert "data-source-uid" in capsys.readouterr().err


def test_migrations_current_command_emits_json(monkeypatch, capsys) -> None:
    import msm.maintenance.migrations as migrations

    result = SimpleNamespace(
        to_payload=lambda: {
            "command": "current",
            "migration_namespace": "mainsequence.markets",
            "expected_revisions": ["0001_baseline"],
            "migration_registry_uid": "migration-registry-uid",
            "status": {"current_revision": "0001_baseline"},
            "synced": [],
            "applied": [],
            "skipped": [],
            "catalog_rows": [],
            "catalog_status": [],
            "ok": True,
        }
    )
    calls: list[dict[str, object]] = []

    def fake_current_migrations(
        *,
        data_source_uid: str | None = None,
        namespace: str | None = None,
    ):
        calls.append({"data_source_uid": data_source_uid, "namespace": namespace})
        return result

    monkeypatch.setattr(migrations, "current_migrations", fake_current_migrations)

    exit_code = cli_main.migrations_current_command(
        data_source_uid="data-source-uid",
        namespace="mainsequence.markets",
        emit_json=True,
    )

    assert exit_code == 0
    assert calls == [
        {
            "data_source_uid": "data-source-uid",
            "namespace": "mainsequence.markets",
        }
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["expected_revisions"] == ["0001_baseline"]


def test_migrations_current_command_reports_sdk_error(monkeypatch, capsys) -> None:
    import msm.maintenance.migrations as migrations

    def fake_current_migrations(
        *,
        data_source_uid: str | None = None,
        namespace: str | None = None,
    ):
        raise migrations.MigrationSupportError("SDK migration API is missing")

    monkeypatch.setattr(migrations, "current_migrations", fake_current_migrations)

    exit_code = cli_main.migrations_current_command(emit_json=True)

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SDK migration API is missing" in captured.err
