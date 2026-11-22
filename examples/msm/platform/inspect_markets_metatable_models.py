from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from msm.models import markets_sqlalchemy_models  # noqa: E402


def describe_markets_metatable_models() -> list[dict[str, str]]:
    """Return the platform-managed table names of the markets models."""

    rows: list[dict[str, str]] = []
    for model in markets_sqlalchemy_models():
        rows.append(
            {
                "model": model.__name__,
                "identifier": model.metatable_identifier(),
                "schema": str(model.__table__.schema),
                "table_name": model.__table__.name,
            }
        )
    return rows


def main() -> None:
    for row in describe_markets_metatable_models():
        print(
            "{model}: {schema}.{table_name} ({identifier})".format(
                **row,
            )
        )


if __name__ == "__main__":
    main()
