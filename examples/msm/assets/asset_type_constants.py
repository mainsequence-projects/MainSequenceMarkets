from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from msm.constants import (
    ASSET_TYPE_BOND,
    ASSET_TYPE_CRYPTO,
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_SPOT,
    ASSET_TYPE_EQUITY,
    ASSET_TYPE_FUTURE,
    BUILT_IN_ASSET_TYPE_DEFINITIONS,
)


def built_in_asset_type_payloads() -> list[dict[str, str]]:
    """Return `AssetType.upsert(...)` payloads for built-in asset type keys."""

    return [definition.as_payload() for definition in BUILT_IN_ASSET_TYPE_DEFINITIONS]


def main() -> None:
    print(
        json.dumps(
            {
                "asset_type_constants": [
                    ASSET_TYPE_CURRENCY,
                    ASSET_TYPE_CURRENCY_SPOT,
                    ASSET_TYPE_BOND,
                    ASSET_TYPE_FUTURE,
                    ASSET_TYPE_CRYPTO,
                    ASSET_TYPE_EQUITY,
                ],
                "asset_type_payloads": built_in_asset_type_payloads(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
