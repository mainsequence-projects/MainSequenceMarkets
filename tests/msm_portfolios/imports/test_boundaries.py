from __future__ import annotations

from pathlib import Path


def test_core_msm_does_not_import_msm_portfolios() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    core_root = repo_root / "src" / "msm"
    offenders: list[str] = []

    for path in core_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if "msm_portfolios" in path.read_text():
            offenders.append(str(path.relative_to(core_root)))

    assert offenders == []
