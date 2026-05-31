from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)
from examples.pricing.utils import (
    EXAMPLE_CURVE_UNIQUE_IDENTIFIER,
    EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
    MockFlatForwardDiscountCurvesNode,
    MockIndexFixingsNode,
    example_index_convention_dump,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm


def create_floating_bond_pricing_workflow() -> dict[str, Any]:
    """Create and price a floating-rate bond from pricing-owned market data."""

    import QuantLib as ql

    msm.start_engine(
        models=[
            "AssetType",
            "Asset",
            "Issuer",
            "BondAssetDetails",
            "IndexType",
            "Index",
        ],
    )

    from msm.api.assets import Asset, AssetType, Bond
    from msm.api.indices import Index, IndexType
    from msm.api.issuers import Issuer
    from msm.constants import (
        ASSET_TYPE_BOND_DEFINITION,
        ASSET_TYPE_CURRENCY,
        ASSET_TYPE_CURRENCY_DEFINITION,
        INDEX_TYPE_INTEREST_RATE,
        INDEX_TYPE_INTEREST_RATE_DEFINITION,
    )
    from msm_pricing.api import (
        AssetCurrentPricingDetails,
        Curve,
        IndexConventionDetails,
        PricingMarketDataBinding,
    )
    from msm_pricing.bootstrap import create_pricing_schemas
    from msm_pricing.data_nodes import CurveConfig, IndexFixingConfiguration
    from msm_pricing.instruments import FloatingRateBond, Instrument
    from msm_pricing.settings import (
        PRICING_CONCEPT_DISCOUNT_CURVES,
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
        PRICING_CONTEXT_DEFAULT,
        PRICING_CONTEXT_EOD,
    )

    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    ql.Settings.instance().evaluationDate = ql.Date(27, 5, 2026)
    _print_step(
        "Set QuantLib valuation date",
        valuation_date=valuation_date.isoformat(),
    )

    create_pricing_schemas(
        models=[
            "Asset",
            "IndexType",
            "Index",
            "IndexConventionDetails",
            "Curve",
            "AssetCurrentPricingDetails",
            "PricingMarketDataBinding",
        ],
    )
    _print_step("Initialized pricing MetaTable runtime")
    default_bindings = PricingMarketDataBinding.filter(
        context_key=PRICING_CONTEXT_DEFAULT,
        limit=10,
    )
    _print_step(
        "Seeded default pricing market-data bindings",
        bindings=[
            {
                "concept_key": binding.concept_key,
                "data_node_identifier": binding.data_node_identifier,
            }
            for binding in default_bindings
            if binding.concept_key
            in {
                PRICING_CONCEPT_DISCOUNT_CURVES,
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
            }
        ],
    )

    bond_asset_type = AssetType.upsert(**ASSET_TYPE_BOND_DEFINITION.as_payload())
    _print_step(
        "Registered bond asset type",
        asset_type=bond_asset_type.asset_type,
    )
    currency_asset_type = AssetType.upsert(**ASSET_TYPE_CURRENCY_DEFINITION.as_payload())
    _print_step(
        "Registered currency asset type",
        asset_type=currency_asset_type.asset_type,
    )
    issuer = Issuer.upsert(
        unique_identifier="MSM-PRICING-EXAMPLE-ISSUER",
        display_name="MSM Pricing Example Issuer",
    )
    _print_step(
        "Registered issuer",
        issuer_uid=issuer.uid,
        unique_identifier=issuer.unique_identifier,
    )
    currency_asset = Asset.upsert(unique_identifier="USD", asset_type=ASSET_TYPE_CURRENCY)
    _print_step(
        "Registered denomination currency asset",
        asset_uid=currency_asset.uid,
        unique_identifier=currency_asset.unique_identifier,
    )
    bond = Bond.upsert(
        unique_identifier="MSM-PRICING-EXAMPLE-FRN-2031",
        issuer_uid=issuer.uid,
        currency_asset_uid=currency_asset.uid,
        issue_date=dt.date(2026, 5, 27),
        maturity_date=dt.date(2031, 5, 27),
        status="ACTIVE",
    )
    _print_step(
        "Registered bond asset",
        asset_uid=bond.asset_uid,
        unique_identifier=bond.unique_identifier,
    )
    bond_asset = Asset.get_by_uid(bond.asset_uid)
    if bond_asset is None:
        raise RuntimeError(f"Expected bond asset {bond.asset_uid} to exist.")
    _print_step(
        "Loaded canonical bond asset",
        asset_uid=bond_asset.uid,
        unique_identifier=bond_asset.unique_identifier,
    )

    index_type = IndexType.upsert(**INDEX_TYPE_INTEREST_RATE_DEFINITION.as_payload())
    _print_step(
        "Registered interest-rate index type",
        index_type=index_type.index_type,
    )
    index = Index.upsert(
        unique_identifier=EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
        index_type=INDEX_TYPE_INTEREST_RATE,
        display_name="USD SOFR Example 3M",
        description="Example USD SOFR-style 3M floating-rate index.",
        provider="example",
    )
    _print_step(
        "Registered floating-rate index",
        index_uid=index.uid,
        index_type=index.index_type,
        unique_identifier=index.unique_identifier,
    )
    convention_details = IndexConventionDetails.upsert(
        index_uid=index.uid,
        index_family="ibor",
        convention_dump=example_index_convention_dump(),
        source="example",
    )
    _print_step(
        "Registered index convention details",
        index_uid=convention_details.index_uid,
        index_family=convention_details.index_family,
    )
    curve = Curve.upsert(
        unique_identifier=EXAMPLE_CURVE_UNIQUE_IDENTIFIER,
        display_name="USD SOFR Example Discount Curve",
        curve_type="discount",
        index_uid=index.uid,
        interpolation_method="log_linear_discount",
        compounding="compounded_annual",
        source="example",
        metadata_json={"example": "flat-forward zero curve"},
    )
    _print_step(
        "Registered discount curve",
        curve_uid=curve.uid,
        unique_identifier=curve.unique_identifier,
    )

    curve_node = MockFlatForwardDiscountCurvesNode(
        CurveConfig(curve_unique_identifier=curve.unique_identifier),
        valuation_date=valuation_date,
        zero_rate=0.05,
    )
    curve_frame = curve_node.run(debug_mode=True, force_update=True)
    _print_step(
        "Published mock discount curve rows",
        rows=len(curve_frame),
        node_identifier=curve_node._default_identifier(),
    )

    fixing_node = MockIndexFixingsNode(
        IndexFixingConfiguration(index_unique_identifiers=[index.unique_identifier]),
        valuation_date=valuation_date,
        fixing_rate=0.0525,
        lookback_days=370,
    )
    fixing_frame = fixing_node.run(debug_mode=True, force_update=True)
    _print_step(
        "Published mock index fixing rows",
        rows=len(fixing_frame),
        node_identifier=fixing_node._default_identifier(),
    )

    eod_curve_binding = PricingMarketDataBinding.upsert(
        context_key=PRICING_CONTEXT_EOD,
        concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        data_node_identifier=curve_node._default_identifier(),
        source="example",
    )
    eod_fixing_binding = PricingMarketDataBinding.upsert(
        context_key=PRICING_CONTEXT_EOD,
        concept_key=PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
        data_node_identifier=fixing_node._default_identifier(),
        source="example",
    )
    _print_step(
        "Registered EOD pricing market-data context",
        context_key=PRICING_CONTEXT_EOD,
        bindings=[
            {
                "concept_key": eod_curve_binding.concept_key,
                "data_node_identifier": eod_curve_binding.data_node_identifier,
            },
            {
                "concept_key": eod_fixing_binding.concept_key,
                "data_node_identifier": eod_fixing_binding.data_node_identifier,
            },
        ],
    )

    _print_step(
        "Using default pricing market-data context",
        context_key=PRICING_CONTEXT_DEFAULT,
        curve_data_node_identifier=curve_node._default_identifier(),
        fixing_data_node_identifier=fixing_node._default_identifier(),
    )

    instrument = FloatingRateBond(
        face_value=100.0,
        issue_date=dt.date(2026, 5, 27),
        maturity_date=dt.date(2031, 5, 27),
        day_count=ql.Actual360(),
        calendar=ql.UnitedStates(ql.UnitedStates.Settlement),
        business_day_convention=ql.ModifiedFollowing,
        settlement_days=2,
        coupon_frequency=ql.Period("3M"),
        floating_rate_index_uid=index.uid,
        spread=0.0015,
    )
    _print_step(
        "Created floating-rate bond instrument",
        floating_rate_index_uid=instrument.floating_rate_index_uid,
        spread=instrument.spread,
    )
    instrument.attach_to_asset(
        bond_asset,
        pricing_details_date=valuation_date,
        source="example",
        metadata_json={
            "workflow": "floating-rate-bond-pricing-example",
            "curve_unique_identifier": curve.unique_identifier,
            "index_unique_identifier": index.unique_identifier,
        },
    )
    _print_step(
        "Attached instrument to bond asset",
        asset_uid=bond_asset.uid,
        instrument_type=type(instrument).__name__,
    )

    stored_pricing_details = AssetCurrentPricingDetails.get_by_asset_uid(bond_asset.uid)
    _print_step(
        "Loaded current pricing details row",
        asset_uid=stored_pricing_details.asset_uid,
        instrument_type=stored_pricing_details.instrument_type,
    )
    loaded_instrument = Instrument.load_from_asset(bond_asset)
    _print_step(
        "Loaded instrument from asset",
        asset_uid=bond_asset.uid,
        instrument_type=type(loaded_instrument).__name__,
    )
    loaded_instrument.set_valuation_date(valuation_date)
    _print_step(
        "Set loaded instrument valuation date",
        valuation_date=valuation_date.isoformat(),
    )

    price = loaded_instrument.price()
    _print_step("Computed bond price", price=price)
    analytics = loaded_instrument.analytics()
    _print_step("Computed bond analytics", fields=len(analytics))
    cashflows = loaded_instrument.get_cashflows()
    _print_step(
        "Computed bond cashflows",
        future_rows=len(cashflows.get("future", [])),
        historical_rows=len(cashflows.get("historical", [])),
    )
    carry_roll_down = loaded_instrument.carry_roll_down(ql.Period("1M"), clean=True)
    _print_step("Computed one-month carry and roll-down", result=carry_roll_down)

    return {
        "bond_asset_type": bond_asset_type,
        "currency_asset_type": currency_asset_type,
        "issuer": issuer,
        "currency_asset": currency_asset,
        "bond_asset": bond_asset,
        "index": index,
        "index_convention_details": convention_details,
        "curve": curve,
        "curve_node_identifier": curve_node._default_identifier(),
        "fixing_node_identifier": fixing_node._default_identifier(),
        "curve_rows": len(curve_frame),
        "fixing_rows": len(fixing_frame),
        "stored_pricing_details": stored_pricing_details,
        "loaded_instrument_type": type(loaded_instrument).__name__,
        "floating_rate_index_uid": str(loaded_instrument.floating_rate_index_uid),
        "price": price,
        "analytics": analytics,
        "cashflows": _preview_cashflows(cashflows),
        "carry_roll_down": carry_roll_down,
    }


def _preview_cashflows(
    cashflows: dict[str, list[dict[str, Any]]],
    *,
    limit: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    return {bucket: rows[:limit] for bucket, rows in cashflows.items() if rows}


def _print_step(message: str, **fields: Any) -> None:
    if not fields:
        print(f"[bond_pricing_example] {message}")
        return

    rendered = ", ".join(f"{key}={value}" for key, value in fields.items())
    print(f"[bond_pricing_example] {message}: {rendered}")


def main() -> None:
    print(json.dumps(create_floating_bond_pricing_workflow(), default=str, indent=2))


if __name__ == "__main__":
    main()
