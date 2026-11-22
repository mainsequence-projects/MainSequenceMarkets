from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from msm.api.assets import Asset
from msm.api.derivatives import Future
from msm.api.indices import Index, IndexType
from msm.constants import INDEX_TYPE_EQUITY, INDEX_TYPE_EQUITY_DEFINITION
from msm.services.assets import openfigi
from tests.support.sqlite_markets import serve_row_operations

INDEX_RESULT = {
    "figi": "BBG000KKFC45",
    "name": "Example Index",
    "securityDescription": "Example Index Description",
    "marketSector": "Index",
}
FUTURE_RESULT = {"figi": "BBG01SWCTHK4", "name": "Example Future", "marketSector": "Equity"}


def test_get_openfigi_api_key_reads_mainsequence_secret(monkeypatch) -> None:
    requested_secret_names = []

    def fake_get_secret(secret_name: str):
        requested_secret_names.append(secret_name)
        return SimpleNamespace(value=SecretStr("test-openfigi-key"))

    monkeypatch.setattr(openfigi, "_get_mainsequence_secret", fake_get_secret)

    assert openfigi.get_openfigi_api_key() == "test-openfigi-key"
    assert requested_secret_names == [openfigi.OPENFIGI_API_KEY_SECRET_NAME]


def test_get_openfigi_api_key_reports_missing_mainsequence_secret(monkeypatch) -> None:
    class DoesNotExist(Exception):
        pass

    def missing_secret(secret_name: str):
        raise DoesNotExist(secret_name)

    monkeypatch.setattr(openfigi, "_get_mainsequence_secret", missing_secret)

    with pytest.raises(openfigi.OpenFigiConfigurationError) as exc_info:
        openfigi.get_openfigi_api_key()

    message = str(exc_info.value)
    assert "OPEN_FIGI_API_KEY needs to be set" in message
    assert "www.main-sequence.app/app/main_sequence_workbench/secrets" in message
    assert "`value_reader` on OPEN_FIGI_API_KEY" in message


def test_get_openfigi_api_key_names_value_reader_when_the_value_is_refused(monkeypatch) -> None:
    from mainsequence.client.exceptions import PermissionDeniedError

    refusal = PermissionDeniedError(
        "You do not have permission to perform this action.",
        payload={"required_action": "read_value", "granting_policies": ["value_reader"]},
    )

    def refused_secret(secret_name: str):
        raise refusal

    monkeypatch.setattr(openfigi, "_get_mainsequence_secret", refused_secret)

    with pytest.raises(openfigi.OpenFigiConfigurationError) as exc_info:
        openfigi.get_openfigi_api_key()

    message = str(exc_info.value)
    assert "`value_reader` on OPEN_FIGI_API_KEY" in message
    assert "secrets: [{name: OPEN_FIGI_API_KEY, policy: value_reader}]" in message
    assert exc_info.value.__cause__ is refusal


def test_get_openfigi_api_key_reports_secret_without_value(monkeypatch) -> None:
    monkeypatch.setattr(
        openfigi,
        "_get_mainsequence_secret",
        lambda secret_name: SimpleNamespace(value=None),
    )

    with pytest.raises(openfigi.OpenFigiConfigurationError, match="OPEN_FIGI_API_KEY"):
        openfigi.get_openfigi_api_key()


def test_openfigi_headers_use_secret_api_key(monkeypatch) -> None:
    monkeypatch.setattr(openfigi, "get_openfigi_api_key", lambda: "from-secret")

    assert openfigi._openfigi_headers() == {
        "Content-Type": "application/json",
        "X-OPENFIGI-APIKEY": "from-secret",
    }


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    serve_row_operations(monkeypatch, sqlite_markets)
    IndexType.upsert(**INDEX_TYPE_EQUITY_DEFINITION.as_payload())
    return sqlite_markets


def test_upsert_index_from_openfigi_result_writes_a_custom_index(markets) -> None:
    index = openfigi.upsert_index_from_openfigi_result(
        INDEX_RESULT,
        index_type=INDEX_TYPE_EQUITY,
        value_format="percent",
    )

    assert Index.get_by_unique_identifier("BBG000KKFC45") == index
    assert index.index_type == INDEX_TYPE_EQUITY
    assert index.display_name == "Example Index"
    assert index.calculation_method == "custom"
    assert index.value_format == "percent"
    assert index.description == "Example Index Description"
    assert index.metadata_json == {
        "openfigi": {
            "figi": "BBG000KKFC45",
            "composite": None,
            "share_class": None,
            "ticker": None,
            "name": "Example Index",
            "exchange_code": None,
            "security_type": None,
            "security_type_2": None,
            "security_market_sector": "Index",
            "security_description": "Example Index Description",
            "unique_id": None,
            "unique_id_fut_opt": None,
            "metadata": None,
            "raw_payload": INDEX_RESULT,
        }
    }


def test_upsert_index_from_openfigi_result_keeps_a_stored_calculation_method(markets) -> None:
    stored = Index.upsert(
        unique_identifier="BBG000KKFC45",
        index_type=INDEX_TYPE_EQUITY,
        display_name="Formula Index",
        calculation_method="formula",
        value_format="decimal",
    )

    index = openfigi.upsert_index_from_openfigi_result(
        INDEX_RESULT,
        index_type=INDEX_TYPE_EQUITY,
        value_format="decimal",
    )

    assert index.uid == stored.uid
    assert index.calculation_method == "formula"


def test_upsert_index_from_openfigi_result_keeps_a_percent_index_and_its_suffix(markets) -> None:
    stored = Index.upsert(
        unique_identifier="BBG000KKFC45",
        index_type=INDEX_TYPE_EQUITY,
        display_name="Percent Index",
        calculation_method="custom",
        value_format="percent",
        value_suffix="p.a.",
    )

    openfigi.upsert_index_from_openfigi_result(
        INDEX_RESULT,
        index_type=INDEX_TYPE_EQUITY,
        value_format="percent",
    )

    index = Index.get_by_unique_identifier("BBG000KKFC45")
    assert index.uid == stored.uid
    assert index.value_format == "percent"
    assert index.value_suffix == "p.a."


def test_upsert_index_from_openfigi_result_requires_index_market_sector() -> None:
    with pytest.raises(ValueError, match="marketSector 'Index'"):
        openfigi.upsert_index_from_openfigi_result(
            {
                "unique_identifier": "BBG000BAD",
                "figi": "BBG000BAD",
                "name": "Not An Index",
                "security_market_sector": "Equity",
            },
            index_type=INDEX_TYPE_EQUITY,
            value_format="decimal",
        )


def test_register_from_figis_writes_the_index_and_its_future(markets, monkeypatch) -> None:
    queries = []
    results = {result["figi"]: result for result in (INDEX_RESULT, FUTURE_RESULT)}

    def fake_query_by_figi(figi_code, **kwargs):
        queries.append((figi_code, kwargs))
        return openfigi.normalize_openfigi_result(results[figi_code])

    monkeypatch.setattr(openfigi, "query_by_figi", fake_query_by_figi)
    access = {"api_key": "test-key", "api_url": "https://example.test/openfigi"}
    currency = Asset.upsert(unique_identifier="USD")
    expires_at = dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC)

    index = openfigi.register_index_from_figi(
        "BBG000KKFC45",
        index_type=INDEX_TYPE_EQUITY,
        value_format="decimal",
        **access,
    )
    future = openfigi.register_index_future_from_figis(
        "BBG01SWCTHK4",
        underlying_index_figi="BBG000KKFC45",
        underlying_index_type=INDEX_TYPE_EQUITY,
        underlying_index_value_format="percent",
        settlement_asset_uid=currency.uid,
        margin_asset_uid=currency.uid,
        kind="EXPIRING",
        quote_unit="INDEX_POINT",
        settlement_model="LINEAR",
        settlement_method="CASH",
        contract_size=Decimal("50"),
        contract_unit="INDEX_POINT",
        expires_at=expires_at,
        settles_at=expires_at,
        metadata={"source": "test"},
        **access,
    )

    assert queries == [
        ("BBG000KKFC45", access),
        ("BBG000KKFC45", access),
        ("BBG01SWCTHK4", access),
    ]
    assert index.value_format == "decimal"
    underlying = Index.get_by_uid(future.underlying_index_uid)
    assert underlying.uid == index.uid
    assert underlying.calculation_method == "custom"
    assert underlying.value_format == "percent"
    assert isinstance(future, Future)
    assert Asset.get_by_uid(future.asset_uid).unique_identifier == "BBG01SWCTHK4"
    assert future.settlement_asset == future.margin_asset == currency.uid
    assert future.contract_size == Decimal("50")
    assert future.expires_at.replace(tzinfo=None) == expires_at.replace(tzinfo=None)
    assert future.metadata["source"] == "test"
    assert future.metadata["underlying_index_figi"] == "BBG000KKFC45"
    assert future.metadata["openfigi"]["figi"] == "BBG01SWCTHK4"
    assert future.metadata["openfigi"]["raw_payload"] == FUTURE_RESULT
