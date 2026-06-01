from __future__ import annotations

import os

os.environ.setdefault("MAIN_SEQUENCE_PROJECT_UID", " ")
os.environ.setdefault("MAIN_SEQUENCE_PROJECT_ID", " ")

from msm.maintenance.migrations import load_migration_specs


DATA_SOURCE_PLACEHOLDER = "<dynamic-table-data-source-uid>"


def main() -> None:
    print("Packaged ms-markets migration revisions:")
    for spec in load_migration_specs():
        identifiers = ", ".join(spec.identifiers)
        print(f"- {spec.revision}: {identifiers}")

    print("\nAdmin command sequence:")
    for command in (
        f"msm migrations current --data-source-uid {DATA_SOURCE_PLACEHOLDER} --json",
        f"msm migrations sync --data-source-uid {DATA_SOURCE_PLACEHOLDER}",
        f"msm migrations upgrade --data-source-uid {DATA_SOURCE_PLACEHOLDER}",
        f"msm migrations validate --data-source-uid {DATA_SOURCE_PLACEHOLDER}",
    ):
        print(command)


if __name__ == "__main__":
    main()
