"""Export the canonical apps/v1 OpenAPI document as deterministic JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from apps.v1.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination JSON file for the generated apps/v1 OpenAPI document.",
    )
    args = parser.parse_args()

    destination = args.output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Exported apps/v1 OpenAPI to {destination}")


if __name__ == "__main__":
    main()
