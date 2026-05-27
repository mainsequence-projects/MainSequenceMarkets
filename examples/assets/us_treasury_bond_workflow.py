from __future__ import annotations

import datetime as dt
import json
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

US_TREASURY_BOND_INPUT = {
    "asset_type": "BOND",
    "issuer": "US_TREASURY",
    "instrument_name": "US Treasury Note 4.375% 2036",
    "maturity_tenor_at_issue": "10Y",
    "coupon_rate": "0.04375",
    "maturity_date": dt.date(2036, 5, 15),
    "identifiers": {
        "CUSIP": "91282CQQ7",
        "FIGI": "BBG0221YLR31",
    },
}
US_TREASURY_ISSUER = {
    "unique_identifier": "US_TREASURY",
    "display_name": "United States Treasury",
}
USD_CURRENCY = {
    "code": "USD",
    "currency_name": "US Dollar",
}
INFERRED_ISSUE_DATE = dt.date(2026, 5, 15)
NON_BOND_DETAIL_FIELDS = {
    "coupon_rate": (
        "Coupon is an instrument/pricing term, not part of the minimal "
        "BondDetailsTable identity contract."
    ),
    "maturity_tenor_at_issue": (
        "Tenor is a source/reference term; BondDetailsTable stores explicit "
        "issue_date and maturity_date."
    ),
}


def register_us_treasury_bond() -> dict[str, Any]:
    """Register a US Treasury bond while preserving provider identifiers."""

    from msm.api.assets import Asset, AssetType, Bond, OpenFigiDetails
    from msm.api.issuers import Issuer

    currency_asset_type = AssetType.upsert(
        asset_type="currency",
        display_name="Currency",
        description="Single currency assets used as denomination units.",
    )
    bond_asset_type = AssetType.upsert(
        asset_type=US_TREASURY_BOND_INPUT["asset_type"],
        display_name="Bond",
        description="Debt instruments represented as tradable assets.",
    )
    issuer = Issuer.upsert(**US_TREASURY_ISSUER)
    currency_asset = Asset.upsert(
        unique_identifier=USD_CURRENCY["code"],
        asset_type="currency",
    )

    identifiers = US_TREASURY_BOND_INPUT["identifiers"]
    bond = Bond.upsert(
        unique_identifier=identifiers["CUSIP"],
        issuer_uid=issuer.uid,
        currency_asset_uid=currency_asset.uid,
        issue_date=INFERRED_ISSUE_DATE,
        maturity_date=US_TREASURY_BOND_INPUT["maturity_date"],
        status="ACTIVE",
    )
    openfigi_details = OpenFigiDetails.upsert(
        asset_uid=bond.asset_uid,
        figi=identifiers["FIGI"],
        name=US_TREASURY_BOND_INPUT["instrument_name"],
        security_market_sector="Govt",
        security_description=US_TREASURY_BOND_INPUT["instrument_name"],
        unique_id=identifiers["CUSIP"],
        metadata_text=json.dumps(
            {
                "cusip": identifiers["CUSIP"],
                "source_field_boundary": NON_BOND_DETAIL_FIELDS,
            },
            sort_keys=True,
        ),
        raw_payload={
            **US_TREASURY_BOND_INPUT,
            "maturity_date": US_TREASURY_BOND_INPUT["maturity_date"].isoformat(),
        },
    )

    return {
        "currency_asset_type": currency_asset_type,
        "bond_asset_type": bond_asset_type,
        "issuer": issuer,
        "currency_asset": currency_asset,
        "bond": bond,
        "bond_asset": Asset.get_by_uid(bond.asset_uid),
        "openfigi_details": openfigi_details,
        "non_bond_detail_fields": NON_BOND_DETAIL_FIELDS,
    }


def main() -> None:
    print(register_us_treasury_bond())


if __name__ == "__main__":
    main()
