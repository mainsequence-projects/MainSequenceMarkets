"""``msm_pricing``'s binding rows and configuration keep the pre-3.0 names (ADR 0048).

Split from ``tests/msm/api/test_renamed_fields.py``, whose values it shares through
``tests/support/renamed_fields.py``.
"""

from __future__ import annotations

import uuid

import pytest

from msm_pricing.api.market_data_bindings import PricingMarketDataSet, PricingMarketDataSetBinding
from msm_pricing.config import PricingMarketDataConfiguration
from tests.support.renamed_fields import STORAGE_TABLE_UID


def test_pricing_binding_rows_and_resolution_keep_the_pre_3_0_names(monkeypatch) -> None:
    binding = PricingMarketDataSetBinding.model_validate(
        {
            "uid": uuid.uuid4(),
            "market_data_set_uid": uuid.uuid4(),
            "concept_key": "discount_curves",
            "data_node_uid": STORAGE_TABLE_UID,
        }
    )
    monkeypatch.setattr(PricingMarketDataSet, "resolve_uid", classmethod(lambda cls, _: uuid.uuid4()))
    monkeypatch.setattr(
        PricingMarketDataSetBinding,
        "get_by_set_and_concept",
        classmethod(lambda cls, **_kwargs: binding),
    )

    assert binding.storage_table_uid == STORAGE_TABLE_UID
    with pytest.warns(DeprecationWarning, match="resolve_data_node_uid is deprecated"):
        resolved = PricingMarketDataSetBinding.resolve_data_node_uid(concept_key="discount_curves")
    assert resolved == STORAGE_TABLE_UID


def test_pricing_configuration_keeps_the_pre_3_0_names() -> None:
    with pytest.warns(DeprecationWarning, match="data_node_uids is deprecated"):
        configuration = PricingMarketDataConfiguration(
            data_node_uids={"discount_curves": str(STORAGE_TABLE_UID)}
        )

    assert configuration.storage_table_uids == {"discount_curves": STORAGE_TABLE_UID}
    with pytest.warns(DeprecationWarning, match="data_node_uids is deprecated"):
        assert configuration.data_node_uids == {"discount_curves": STORAGE_TABLE_UID}
    with pytest.warns(DeprecationWarning, match="direct_data_node_uid_for is deprecated"):
        assert configuration.direct_data_node_uid_for("discount_curves") == STORAGE_TABLE_UID
