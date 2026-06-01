from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm

EXAMPLE_BOND_ISSUER = {
    "unique_identifier": "example-issuer",
    "display_name": "Example Issuer",
}
EXAMPLE_BOND_CURRENCY = {
    "code": "USD",
    "currency_name": "US Dollar",
}
EXAMPLE_BOND_UNIQUE_IDENTIFIER = "example-usd-bond-2031"


def create_example_bond() -> dict[str, Any]:
    """Create an issuer, denomination currency, and bond asset."""

    msm.start_engine(
        models=["AssetType", "Asset", "Issuer", "BondAssetDetails"],
    )

    from msm.api.assets import Asset, AssetType, Bond
    from msm.api.issuers import Issuer
    from msm.constants import (
        ASSET_TYPE_BOND_DEFINITION,
        ASSET_TYPE_CURRENCY,
        ASSET_TYPE_CURRENCY_DEFINITION,
    )

    currency_asset_type = AssetType.upsert(**ASSET_TYPE_CURRENCY_DEFINITION.as_payload())
    bond_asset_type = AssetType.upsert(**ASSET_TYPE_BOND_DEFINITION.as_payload())
    issuer = Issuer.upsert(**EXAMPLE_BOND_ISSUER)
    currency_asset = Asset.upsert(
        unique_identifier=EXAMPLE_BOND_CURRENCY["code"],
        asset_type=ASSET_TYPE_CURRENCY,
    )
    bond = Bond.upsert(
        unique_identifier=EXAMPLE_BOND_UNIQUE_IDENTIFIER,
        issuer_uid=issuer.uid,
        currency_asset_uid=currency_asset.uid,
        issue_date=dt.date(2026, 5, 27),
        maturity_date=dt.date(2031, 5, 27),
        status="ACTIVE",
    )

    return {
        "currency_asset_type": currency_asset_type,
        "bond_asset_type": bond_asset_type,
        "issuer": issuer,
        "currency_asset": currency_asset,
        "bond": bond,
        "bond_asset": Asset.get_by_uid(bond.asset_uid),
    }


def main() -> None:
    print(create_example_bond())


if __name__ == "__main__":
    main()
