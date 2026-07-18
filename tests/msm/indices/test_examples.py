from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_PROJECT_ROOT)]

from examples.msm.indices import (  # noqa: E402
    commodity_calendar_spread,
    delta_hedged_option_index,
    equity_beta_spread,
    m_bond_2s5s_yield_spread,
    weighted_multi_leg_spreads,
)


def test_m_bond_example_publishes_basis_points_and_resolved_monthly_bonds() -> None:
    output = m_bond_2s5s_yield_spread.run()

    assert output["values"]["value"].tolist() == pytest.approx([117.0, 120.0])
    assert len(output["resolved_legs"]) == 4
    assert set(output["historical_meaning"]) == {
        m_bond_2s5s_yield_spread.ROLLING_IDENTIFIER,
        m_bond_2s5s_yield_spread.CURRENT_CONSTITUENTS_HISTORY_IDENTIFIER,
    }


def test_commodity_example_separates_fixed_and_rolling_contract_histories() -> None:
    output = commodity_calendar_spread.run()

    assert output["fixed_values"]["value"].tolist() == pytest.approx([2.0, 3.0])
    assert output["rolling_values"]["value"].tolist() == pytest.approx([2.0, 1.5])
    assert len(output["resolved_legs"]) == 4


def test_multi_leg_example_calculates_butterfly_and_unit_normalized_crack() -> None:
    output = weighted_multi_leg_spreads.run()

    assert output["butterfly"]["value"].tolist() == pytest.approx([0.0, 10.0])
    assert output["crack_spread"]["value"].tolist() == pytest.approx([63.0, 72.6])


def test_equity_beta_example_persists_lagged_coefficients_without_lookahead() -> None:
    output = equity_beta_spread.run()

    assert output["no_lookahead"] is True
    assert not output["values"].empty
    assert not output["resolved_legs"].empty


def test_delta_example_distinguishes_current_mark_from_self_financing_performance() -> None:
    output = delta_hedged_option_index.run()

    assert len(output["current_mark"]) == 5
    assert len(output["performance"]) == 5
    assert output["performance"].iloc[0]["value"] == pytest.approx(100.0)
    assert output["performance_uses_prior_positions"] is True
    assert len(output["resolved_deltas"]) == 5
