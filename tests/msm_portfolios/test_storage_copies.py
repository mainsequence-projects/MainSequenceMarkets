"""The real copier keeps one identity per source and target (``msm_portfolios`` storages).

Split from ``tests/msm/test_storage_copies.py``, whose frames it shares through
``tests/support/storage_copies.py``.
"""

from __future__ import annotations

from msm.storage_copies import TimeIndexRowsCopyConfiguration
from tests.support.storage_copies import DAY, _frame


def test_the_real_copier_keeps_one_identity_per_source_and_target() -> None:
    from metatables import TimeIndexMetaTable
    from msm.storage_copies import TimeIndexRowsCopy, registered_time_index_meta_table
    from msm_portfolios.time_index.contract_instances import (
        configured_portfolio_event_ledger_storage,
    )

    instance = configured_portfolio_event_ledger_storage(
        instance_key="copytest", namespace="my-provider", storage_app="my_provider"
    )
    before = dict(vars(instance))
    instance._bind_meta_table(
        TimeIndexMetaTable.model_construct(
            uid="instance-uid",
            data_source_uid="00000000-0000-0000-0000-000000000001",
            identifier=instance.__metatable_identifier__,
        )
    )
    try:
        def copier(source_uid: str) -> TimeIndexRowsCopy:
            config = TimeIndexRowsCopyConfiguration(
                source_table_uid=source_uid, key_column="portfolio_identifier"
            )
            return TimeIndexRowsCopy(config, output_table=instance)

        first = copier("core-uid").set_rows(_frame([(DAY[0], "P1", "A", 0.5)]))
        assert first.update_hash == copier("core-uid").update_hash
        assert first.update_hash != copier("other-uid").update_hash
        assert len(first.update()) == 1 and first.dependencies() == {}
        assert registered_time_index_meta_table(instance).uid == "instance-uid"
    finally:
        for name in set(vars(instance)) - set(before):
            delattr(instance, name)
        for name, value in before.items():
            if vars(instance).get(name) is not value:
                setattr(instance, name, value)
