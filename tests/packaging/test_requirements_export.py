"""Main Sequence images install requirements.txt only, so it must match uv.lock."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)")


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_requirements_pins_match_the_lockfile():
    # Regenerate with `mainsequence code-repository sync` after a dependency change.
    lock = tomllib.loads((REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {_canonical(package["name"]): package["version"] for package in lock["package"]}
    pins = {
        _canonical(match[1]): match[2]
        for line in (REPOSITORY_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if (match := PIN.match(line))
    }

    assert pins
    assert {name: version for name, version in pins.items() if locked.get(name) != version} == {}
