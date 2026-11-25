"""One interpolation configuration is one table, declared by the producer that writes it (#95).

The key is the configuration's: the source's physical table name and cadence, the upsample
frequency and the interpolation rule. So one committed revision names the table in every
Environment, whatever UID the source has there.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import (
    TimeIndexMetaTable,
    TimeIndexTableRef,
    schema_table_name,
    sqlalchemy_naming_convention,
)
from msm_portfolios.contrib.prices.updaters import InterpolatedPrices, InterpolatedPricesConfig
from msm_portfolios.time_index.prices.storage import (
    ExternalPricesInstance,
    InterpolatedPricesInstance,
    InterpolatedPricesStorage,
    interpolated_prices_instance_key,
)
from tests.support.pinned_identities import DATA_SOURCE_UID, PRICES_TABLE_UID, _bound

BARS = "my_provider__bars_1d"
DEVELOPMENT_BARS_UID = "d0000000-0000-4000-8000-000000000001"
PRODUCTION_BARS_UID = "e0000000-0000-4000-8000-000000000001"
CONFIGURATION = {
    "source_table_name": BARS,
    "source_cadence": "1d",
    "upsample_frequency_id": "1d",
    "intraday_bar_interpolation_rule": "ffill",
}


def _key(**changed: Any) -> str:
    return interpolated_prices_instance_key(**{**CONFIGURATION, **changed})


def _table(
    contract: type = InterpolatedPricesInstance,
    *,
    cadence: str | None = "1d",
    storage_app: str = "my_provider",
    **changed: Any,
) -> type:
    """A provider's table, declared on a base of its own for each case."""

    class ProviderBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    attributes = {
        "__instance_key__": _key(**changed),
        "__metatable_namespace__": "my-provider",
        "__markets_storage_app__": storage_app,
    }
    if cadence is not None:
        attributes["__cadence__"] = cadence
    return type("ProviderInterpolatedPrices", (contract, ProviderBase), attributes)


def _bars(
    uid: str = DEVELOPMENT_BARS_UID, *, name: str = BARS, cadence: str = "1d"
) -> TimeIndexTableRef:
    return TimeIndexTableRef(
        output_table=TimeIndexMetaTable.model_construct(
            uid=uid,
            data_source_uid=DATA_SOURCE_UID,
            physical_table_name=name,
            time_indexed_profile=None,
            cadence=cadence,
        )
    )


def _registered(table: type, uid: str = PRICES_TABLE_UID, **metadata: Any):
    """``table`` bound as its migration registers it: with the cadence it declares."""

    return _bound(table, uid, **{"cadence": getattr(table, "__cadence__", None), **metadata})


def _configuration(**changed: Any) -> InterpolatedPricesConfig:
    changed.setdefault("source_price_instance", _bars())
    return InterpolatedPricesConfig(
        **{
            "asset_list": ["ASSET_A"],
            "intraday_bar_interpolation_rule": "ffill",
            "upsample_frequency_id": "1d",
            **changed,
        }
    )


# The key ---------------------------------------------------------------------------------------


def test_each_of_the_four_values_is_part_of_the_key() -> None:
    changed = (
        {"source_table_name": "my_provider__other_bars_1d"},
        {"source_cadence": "5m"},
        {"upsample_frequency_id": "5m"},
        {"intraday_bar_interpolation_rule": "None"},
    )

    assert len({_key(), *(_key(**change) for change in changed)}) == 5


@pytest.mark.parametrize(
    "same",
    [
        {"source_cadence": " 1D "},
        {"upsample_frequency_id": " 1D "},
        {"upsample_frequency_id": None},
        {"upsample_frequency_id": ""},
        {"source_table_name": f" {BARS} "},
        {"intraday_bar_interpolation_rule": " ffill "},
    ],
)
def test_the_key_reads_a_cadence_as_the_updater_does(same) -> None:
    assert _key(**same) == _key()


@pytest.mark.parametrize("empty", [None, "", "  "])
@pytest.mark.parametrize(
    "argument", ["source_table_name", "source_cadence", "intraday_bar_interpolation_rule"]
)
def test_the_key_needs_the_source_and_the_rule(argument, empty) -> None:
    with pytest.raises(ValueError, match=argument):
        _key(**{argument: empty})


# The updater -----------------------------------------------------------------------------------


def test_one_table_serves_a_configuration_whatever_uid_its_source_has() -> None:
    table = _table()

    assert table.__table__.name == schema_table_name(
        "my_provider", "interpolatedpricests", suffix=_key()
    )
    assert table.__metatable_identifier__ == f"my-provider.InterpolatedPricesTS.{_key()}"
    with _registered(table):
        for uid in (DEVELOPMENT_BARS_UID, PRODUCTION_BARS_UID):
            source = _bars(uid)
            prices = InterpolatedPrices(_configuration(source_price_instance=source), output_table=table)

            assert prices.output_table is table
            assert prices.bars_ts is source


def test_the_bound_table_is_where_rows_land_and_not_the_update_identity() -> None:
    one, other = _table(), _table(storage_app="other_provider")
    with _registered(one), _registered(other, "c0000000-0000-4000-8000-000000000001"):
        configuration = _configuration()
        first = InterpolatedPrices(configuration, output_table=one)
        second = InterpolatedPrices(configuration, output_table=other)

    assert (first.output_table, second.output_table) == (one, other)
    assert first.update_hash == second.update_hash
    assert "output_table" not in first.build_configuration


@pytest.mark.parametrize(
    ("source_cadence", "upsample", "table_source_cadence", "table_cadence"),
    [(" 1D", " 1D", "1d", "1d"), (" 1D", None, "1d", "1d"), ("5M", "15M", "5m", "15m")],
)
def test_the_updater_normalizes_as_the_migration_does(
    source_cadence, upsample, table_source_cadence, table_cadence
) -> None:
    table = _table(
        source_cadence=table_source_cadence,
        upsample_frequency_id=table_cadence,
        cadence=table_cadence,
    )
    with _registered(table):
        prices = InterpolatedPrices(
            _configuration(
                source_price_instance=_bars(cadence=source_cadence),
                upsample_frequency_id=upsample,
            ),
            output_table=table,
        )

    assert (prices.bar_frequency_id, prices.upsample_frequency_id) == (
        table_source_cadence,
        table_cadence,
    )


OTHER_TABLES = {
    "another contract": lambda: _table(ExternalPricesInstance),
    "another source": lambda: _table(source_table_name="my_provider__other_bars_1d"),
    "another source cadence": lambda: _table(source_cadence="5m"),
    "another upsample frequency": lambda: _table(upsample_frequency_id="5m"),
    "another rule": lambda: _table(intraday_bar_interpolation_rule="None"),
    "another cadence": lambda: _table(cadence="5m"),
    "no cadence": lambda: _table(cadence=None),
    "the contract's own class": lambda: InterpolatedPricesStorage,
    "no table": lambda: None,
}


@pytest.mark.parametrize("case", OTHER_TABLES)
def test_interpolated_prices_refuses_a_table_its_configuration_does_not_produce(case) -> None:
    table = OTHER_TABLES[case]()
    # Bound, so that only the check can refuse it.
    with nullcontext() if table is None else _registered(table):
        with pytest.raises(ValueError, match="class statement on InterpolatedPricesInstance") as refused:
            InterpolatedPrices(_configuration(), output_table=table)

    assert _key() in str(refused.value)


@pytest.mark.parametrize("registered", [None, "5m"])
def test_interpolated_prices_refuses_a_table_registered_with_another_cadence(registered) -> None:
    # The catalog follows a corrected class when its provider's upgrade runs (MetaTables#131).
    table = _table()
    with _registered(table, cadence=registered):
        with pytest.raises(ValueError, match="metatables migrations upgrade"):
            InterpolatedPrices(_configuration(), output_table=table)


def test_interpolated_prices_requires_its_output_table() -> None:
    with pytest.raises(TypeError, match="output_table"):
        InterpolatedPrices(_configuration())


def test_interpolated_prices_refuses_an_unknown_argument() -> None:
    table = _table()
    with _registered(table):
        with pytest.raises(TypeError, match="unexpected"):
            InterpolatedPrices(_configuration(), output_table=table, unexpected="value")
