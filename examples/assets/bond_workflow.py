from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)

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

    from msm.api.assets import Asset, AssetType, Bond
    from msm.api.issuers import Issuer

    currency_asset_type = AssetType.upsert(
        asset_type="currency",
        display_name="Currency",
        description="Single currency assets used as denomination units.",
    )
    bond_asset_type = AssetType.upsert(
        asset_type="bond",
        display_name="Bond",
        description="Debt instruments represented as tradable assets.",
    )
    issuer = Issuer.upsert(**EXAMPLE_BOND_ISSUER)
    currency_asset = Asset.upsert(
        unique_identifier=EXAMPLE_BOND_CURRENCY["code"],
        asset_type="currency",
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
