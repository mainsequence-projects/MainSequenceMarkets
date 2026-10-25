from __future__ import annotations

from pathlib import Path


def test_core_msm_does_not_import_msm_portfolios() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    core_root = repo_root / "src" / "msm"
    # These name msm_portfolios as a string (moved module paths, or the Markets packages
    # whose row classes run on the remote backend); they import nothing from it.
    allowed_cross_package_files = {"migrations/registry.py", "identity.py", "api/remote.py"}
    offenders: list[str] = []

    for path in core_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative_path = str(path.relative_to(core_root))
        if relative_path in allowed_cross_package_files:
            continue
        if "msm_portfolios" in path.read_text():
            offenders.append(relative_path)

    assert offenders == []
