from __future__ import annotations

import datetime as dt
import json
import sys
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm_pricing.utils import (  # noqa: E402
    EXAMPLE_CURVE_UNIQUE_IDENTIFIER,
    EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
    build_flat_forward_zero_curve,
    build_mock_fixings_frame,
    example_index_convention_dump,
)
from msm.api.indices import Index  # noqa: E402
from msm_pricing.api.curve_building_details import CurveBuildingDetails  # noqa: E402
from msm_pricing.api.curves import Curve  # noqa: E402
from msm_pricing.api.index_convention_details import IndexConventionDetails  # noqa: E402
from msm_pricing.api.market_data_bindings import (  # noqa: E402
    PricingMarketDataSetBinding,
    PricingMarketDataSetCurveBinding,
    curve_binding_key,
)
from msm_pricing.data_interface.data_interface import MSDataInterface  # noqa: E402
from msm_pricing.instruments import Instrument  # noqa: E402
from msm_pricing.settings import (  # noqa: E402
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
)
from msm_pricing.valuation import PricingValuationContext, ValuationLine, ValuationPosition  # noqa: E402

MOCK_MARKET_DATA_SET_UID = uuid.UUID("00000000-0000-4000-8000-000000000001")
MOCK_INDEX_UID = uuid.UUID("00000000-0000-4000-8000-000000000002")
MOCK_CURVE_UID = uuid.UUID("00000000-0000-4000-8000-000000000003")
MOCK_DISCOUNT_CURVES_NODE_UID = uuid.UUID("00000000-0000-4000-8000-000000000004")
MOCK_FIXINGS_NODE_UID = uuid.UUID("00000000-0000-4000-8000-000000000005")


class MockCurvePricedInstrument(Instrument):
    """Small example instrument priced from mock curve and fixing inputs."""

    notional: float
    spread: float
    floating_rate_index_uid: uuid.UUID
    mock_curve_nodes: dict[int, float]
    mock_fixing_rows: list[dict[str, Any]]

    def price(
        self,
        *,
        market_data_set: uuid.UUID | None = None,
        curve_quote_side: str | None = None,
    ) -> float:
        if self.valuation_date is None:
            raise RuntimeError("valuation_date was not prepared")
        if market_data_set != MOCK_MARKET_DATA_SET_UID:
            raise RuntimeError("market_data_set was not injected from the prepared context")
        if curve_quote_side != "mid":
            raise RuntimeError("curve_quote_side was not injected from the prepared context")

        one_year_zero = float(self.mock_curve_nodes[365])
        last_fixing = float(self.mock_fixing_rows[-1]["rate"])
        next_coupon_rate = last_fixing + self.spread
        return self.notional * (1.0 + next_coupon_rate) / (1.0 + one_year_zero)

    def analytics(
        self,
        *,
        market_data_set: uuid.UUID | None = None,
        curve_quote_side: str | None = None,
    ) -> dict[str, float]:
        one_year_zero = float(self.mock_curve_nodes[365])
        last_fixing = float(self.mock_fixing_rows[-1]["rate"])
        return {
            "unit_price": self.price(
                market_data_set=market_data_set,
                curve_quote_side=curve_quote_side,
            ),
            "one_year_zero_rate": one_year_zero,
            "last_fixing_rate": last_fixing,
            "curve_nodes": float(len(self.mock_curve_nodes)),
            "fixing_rows": float(len(self.mock_fixing_rows)),
        }

    def z_spread(
        self,
        target_dirty_ccy: float,
        *,
        market_data_set: uuid.UUID | None = None,
        curve_quote_side: str | None = None,
        discount_curve: Any = None,
    ) -> float:
        if discount_curve is not None:
            raise RuntimeError("mock example does not use explicit discount_curve overrides")
        model_dirty_ccy = self.price(
            market_data_set=market_data_set,
            curve_quote_side=curve_quote_side,
        )
        return (model_dirty_ccy - float(target_dirty_ccy)) / self.notional


def build_mock_context_workflow() -> dict[str, Any]:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    mock_curve_nodes = build_flat_forward_zero_curve(
        valuation_date=valuation_date,
        zero_rate=0.05,
    )
    mock_fixing_frame = build_mock_fixings_frame(
        index_identifier=EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
        valuation_date=valuation_date,
        fixing_rate=0.0525,
    )
    mock_fixing_rows = [
        {**row, "time_index": str(row["time_index"])}
        for row in mock_fixing_frame.to_dict("records")
    ]

    instrument = MockCurvePricedInstrument(
        notional=100.0,
        spread=0.001,
        floating_rate_index_uid=MOCK_INDEX_UID,
        mock_curve_nodes=mock_curve_nodes,
        mock_fixing_rows=mock_fixing_rows,
    )
    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set="mock",
        lines=[ValuationLine(instrument=instrument, units=4.0)],
    )

    with mock_pricing_row_apis():
        context = PricingValuationContext.prepare_for_position(
            position,
            curve_quote_side="mid",
        )
        prepared = context.prepare_instrument(instrument)
        if prepared.instrument is instrument:
            raise RuntimeError("prepared instrument unexpectedly reused the caller object")
        if instrument.valuation_date is not None:
            raise RuntimeError("caller-owned instrument was mutated")

        unit_price = prepared.price()
        observed_dirty_ccy = unit_price - 0.25
        return {
            "market_value": position.price(context=context),
            "unit_price": unit_price,
            "prepared_analytics": prepared.analytics(),
            "prepared_z_spread": prepared.z_spread(observed_dirty_ccy),
            "z_spread_target_dirty_ccy": observed_dirty_ccy,
            "original_valuation_date": instrument.valuation_date,
            "prepared_valuation_date": prepared.instrument.valuation_date.isoformat(),
            "cached_curve_identifier": context.get_curve(
                MOCK_CURVE_UID
            ).unique_identifier,
            "cached_index_family": context.get_index_convention(
                MOCK_INDEX_UID
            ).index_family,
            "mock_curve_nodes": len(mock_curve_nodes),
            "mock_fixing_rows": len(mock_fixing_rows),
        }


@contextmanager
def mock_pricing_row_apis():
    binding_key = curve_binding_key(
        role_key="projection",
        selector_type="index",
        selector_key=str(MOCK_INDEX_UID),
        quote_side="mid",
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "msm_pricing.api.market_data_bindings.PricingMarketDataSet.resolve_uid",
                staticmethod(lambda _selector=None: MOCK_MARKET_DATA_SET_UID),
            )
        )
        stack.enter_context(
            patch(
                "msm_pricing.api.market_data_bindings.PricingMarketDataSetBinding.filter_for_set_and_concepts",
                staticmethod(
                    lambda **_kwargs: [
                        PricingMarketDataSetBinding(
                            uid=uuid.UUID("00000000-0000-4000-8000-000000000006"),
                            market_data_set_uid=MOCK_MARKET_DATA_SET_UID,
                            concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
                            data_node_uid=MOCK_DISCOUNT_CURVES_NODE_UID,
                            storage_table_identifier="mock.discount_curves",
                        ),
                        PricingMarketDataSetBinding(
                            uid=uuid.UUID("00000000-0000-4000-8000-000000000007"),
                            market_data_set_uid=MOCK_MARKET_DATA_SET_UID,
                            concept_key=PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
                            data_node_uid=MOCK_FIXINGS_NODE_UID,
                            storage_table_identifier="mock.index_fixings",
                        ),
                    ]
                ),
            )
        )
        stack.enter_context(
            patch.object(
                Index,
                "filter_by_uids",
                staticmethod(
                    lambda _index_uids: [
                        Index(
                            uid=MOCK_INDEX_UID,
                            unique_identifier=EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
                            index_type="interest_rate",
                            display_name="Example SOFR index",
                            provider="mock",
                        )
                    ]
                ),
            )
        )
        stack.enter_context(
            patch(
                "msm_pricing.api.index_convention_details.IndexConventionDetails.filter_by_index_uids",
                staticmethod(
                    lambda _index_uids: [
                        IndexConventionDetails(
                            index_uid=MOCK_INDEX_UID,
                            index_family="ibor",
                            convention_dump=example_index_convention_dump(),
                            source="mock",
                        )
                    ]
                ),
            )
        )
        stack.enter_context(
            patch(
                "msm_pricing.api.market_data_bindings.PricingMarketDataSetCurveBinding.filter_by_binding_keys",
                staticmethod(
                    lambda **_kwargs: [
                        PricingMarketDataSetCurveBinding(
                            uid=uuid.UUID("00000000-0000-4000-8000-000000000008"),
                            market_data_set_uid=MOCK_MARKET_DATA_SET_UID,
                            binding_key=binding_key,
                            role_key="projection",
                            selector_type="index",
                            selector_key=str(MOCK_INDEX_UID),
                            quote_side="mid",
                            curve_uid=MOCK_CURVE_UID,
                        )
                    ]
                ),
            )
        )
        stack.enter_context(
            patch(
                "msm_pricing.api.curves.Curve.filter_by_uids",
                staticmethod(
                    lambda _curve_uids: [
                        Curve(
                            uid=MOCK_CURVE_UID,
                            unique_identifier=EXAMPLE_CURVE_UNIQUE_IDENTIFIER,
                            display_name="Mock flat-forward projection curve",
                            curve_type="projection",
                            currency_code="USD",
                            quote_side="mid",
                            source="mock",
                        )
                    ]
                ),
            )
        )
        stack.enter_context(
            patch(
                "msm_pricing.api.curve_building_details.CurveBuildingDetails.filter_by_curve_uids",
                staticmethod(
                    lambda _curve_uids: [
                        CurveBuildingDetails(
                            curve_uid=MOCK_CURVE_UID,
                            builder_type="zero_rate_curve",
                            quote_convention="zero_rate",
                            rate_unit="decimal",
                            day_counter_code="Actual360",
                            calendar_code="TARGET",
                            interpolation_method="log_linear_discount",
                            compounding="simple",
                            extrapolation_policy="enabled",
                            source="mock",
                        )
                    ]
                ),
            )
        )
        stack.enter_context(
            patch.object(
                MSDataInterface,
                "get_historical_discount_curve_observations",
                lambda self, curve_names, target_date, *, market_data_set=None: {
                    EXAMPLE_CURVE_UNIQUE_IDENTIFIER: (
                        {
                            "curve_identifier": EXAMPLE_CURVE_UNIQUE_IDENTIFIER,
                            "time_index": target_date,
                            "nodes": [
                                {"days_to_maturity": days, "zero": zero}
                                for days, zero in build_flat_forward_zero_curve(
                                    valuation_date=target_date,
                                    zero_rate=0.05,
                                ).items()
                            ],
                            "key_nodes": None,
                            "metadata_json": {"source": "mock"},
                        },
                        target_date,
                    )
                },
            )
        )
        stack.enter_context(
            patch.object(
                MSDataInterface,
                "get_historical_fixings_for_identifiers",
                lambda self, identifiers, start_date, end_date, *, market_data_set=None: {
                    EXAMPLE_INDEX_UNIQUE_IDENTIFIER: build_mock_fixings_frame(
                        index_identifier=EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
                        valuation_date=end_date,
                        fixing_rate=0.0525,
                    )
                    .assign(time_index=lambda frame: frame["time_index"].dt.date)
                    .set_index("time_index")["rate"]
                    .to_dict()
                },
            )
        )
        yield


def main() -> None:
    print(json.dumps(build_mock_context_workflow(), default=str, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
