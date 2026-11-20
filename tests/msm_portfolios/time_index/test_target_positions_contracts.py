"""TargetPositionsStorage is in both the core and the portfolio model graphs.

Split from ``tests/msm/time_index/test_target_positions_contracts.py``.
"""

from __future__ import annotations

from msm.models import markets_sqlalchemy_models
from msm.time_index.accounts.storage import TargetPositionsStorage
from msm_portfolios.models import portfolio_sqlalchemy_models


def test_target_positions_storage_belongs_to_core_account_model_graph() -> None:
    assert TargetPositionsStorage in set(markets_sqlalchemy_models())
    assert TargetPositionsStorage in set(portfolio_sqlalchemy_models())
