from __future__ import annotations

import importlib
import json
import pathlib

import pytest

from cli.main import bundled_msm_skills_root, main, source_tree_msm_skills_root

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


def test_msm_skills_source_of_truth_is_root_agents() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]

    assert source_tree_msm_skills_root() == repo_root / ".agents" / "skills" / "ms_markets"
    assert bundled_msm_skills_root() == source_tree_msm_skills_root()
    assert not (repo_root / "src" / "msm" / ".agents").exists()


def test_derived_index_workflow_skill_is_in_packaged_bundle() -> None:
    assert "indices/derived_index_workflow" in _bundled_skill_paths()


def test_copy_msm_skills_dry_run_writes_nothing(tmp_path, capsys) -> None:
    exit_code = main(["copy-msm-skills", "--path", str(tmp_path), "--dry-run", "--json"])

    assert exit_code == 0
    assert not (tmp_path / ".agents").exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["destination_root"] == str(tmp_path / ".agents" / "skills" / "ms_markets")
    assert payload["library_name"] == "ms-markets"
    assert payload["namespace"] == "ms_markets"
    assert payload["sentinel_path"] == str(
        tmp_path / ".agents" / "skills" / "ms_markets" / "PINNED_FROM.txt"
    )
    assert sorted(item["name"] for item in payload["updated"]) == _bundled_bundle_names()


def test_copy_msm_skills_blocks_ms_markets_source_checkout(capsys) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    source_root = source_tree_msm_skills_root()
    before = _bundled_skill_paths()

    exit_code = main(["copy-msm-skills", "--path", str(repo_root)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot run inside the ms-markets source checkout" in captured.err
    assert source_root.is_dir()
    assert _bundled_skill_paths() == before


def test_copy_msm_skills_blocks_ms_markets_source_checkout_json(capsys) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]

    exit_code = main(
        [
            "copy-msm-skills",
            "--path",
            str(repo_root),
            "--dry-run",
            "--json",
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["blocked"] is True
    assert payload["dry_run"] is True
    assert payload["project"] == str(repo_root)
    assert payload["destination_root"] == str(source_tree_msm_skills_root())
    assert payload["updated_count"] == 0
    assert payload["updated"] == []
    assert "cannot run inside the ms-markets source checkout" in payload["reason"]


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
    pin_file = tmp_path / ".agents" / "skills" / "ms_markets" / "PINNED_FROM.txt"
    pin_content = pin_file.read_text(encoding="utf-8")
    assert "library_name=ms-markets" in pin_content
    assert "namespace=ms_markets" in pin_content
    assert "command=msm copy-msm-skills" in pin_content
    assert "pinned_version=" in pin_content
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


def test_msm_cli_does_not_expose_schema_admin_commands() -> None:
    help_text = cli_main._build_parser().format_help()

    assert "migrations" not in help_text


def test_migrations_command_is_rejected(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["migrations"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid choice" in captured.err
