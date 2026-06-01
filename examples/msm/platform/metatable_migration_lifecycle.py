from __future__ import annotations

import os

os.environ.setdefault("MAIN_SEQUENCE_PROJECT_UID", " ")
os.environ.setdefault("MAIN_SEQUENCE_PROJECT_ID", " ")

from msm.maintenance.migrations import load_migration_specs


def main() -> None:
    print("Packaged ms-markets migration revisions:")
    for spec in load_migration_specs():
        identifiers = ", ".join(spec.identifiers)
        print(f"- {spec.revision}: {identifiers}")

    print("\nAdmin command sequence:")
    for command in (
        "msm migrations current --json",
        "msm migrations sync",
        "msm migrations upgrade",
        "msm migrations validate",
    ):
        print(command)


if __name__ == "__main__":
    main()
