from __future__ import annotations

import json

from msm.cli import bundled_msm_skills_root, main


def _bundled_skill_names() -> list[str]:
    return sorted(
        item.name
        for item in bundled_msm_skills_root().iterdir()
        if item.is_dir() and not item.name.startswith(".") and not item.name.startswith("__")
    )


def test_import_msm_does_not_copy_skills(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    import msm  # noqa: F401

    assert not (tmp_path / ".agents").exists()


def test_copy_msm_skills_dry_run_writes_nothing(tmp_path, capsys) -> None:
    exit_code = main(["copy-msm-skills", "--path", str(tmp_path), "--dry-run", "--json"])

    assert exit_code == 0
    assert not (tmp_path / ".agents").exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["destination_root"] == str(tmp_path / ".agents" / "ms_markets")
    assert sorted(item["name"] for item in payload["updated"]) == _bundled_skill_names()


def test_copy_msm_skills_copies_only_ms_markets_namespace(tmp_path) -> None:
    mainsequence_skill = tmp_path / ".agents" / "skills" / "mainsequence" / "project_builder"
    mainsequence_skill.mkdir(parents=True)
    sentinel = mainsequence_skill / "SKILL.md"
    sentinel.write_text("keep me", encoding="utf-8")

    stale_skill = tmp_path / ".agents" / "ms_markets" / _bundled_skill_names()[0]
    stale_skill.mkdir(parents=True)
    stale_file = stale_skill / "stale.txt"
    stale_file.write_text("remove me", encoding="utf-8")

    exit_code = main(["copy-msm-skills", "--path", str(tmp_path)])

    assert exit_code == 0
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert not stale_file.exists()
    for skill_name in _bundled_skill_names():
        skill_file = tmp_path / ".agents" / "ms_markets" / skill_name / "SKILL.md"
        assert skill_file.exists()
