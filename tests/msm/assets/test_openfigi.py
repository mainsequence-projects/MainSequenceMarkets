from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from msm.services.assets import openfigi


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


def test_upsert_index_from_openfigi_result_requires_index_market_sector(
    monkeypatch,
) -> None:
    calls = []
    index_uid = uuid.uuid4()

    def fake_index_upsert(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(uid=index_uid, **kwargs)

    monkeypatch.setattr("msm.api.indices.Index.upsert", fake_index_upsert)

    index = openfigi.upsert_index_from_openfigi_result(
        {
            "unique_identifier": "BBG000KKFC45",
            "figi": "BBG000KKFC45",
            "name": "Example Index",
            "security_description": "Example Index Description",
            "security_market_sector": "Index",
            "raw_payload": {"figi": "BBG000KKFC45"},
        }
    )

    assert index.uid == index_uid
    assert calls == [
        {
            "unique_identifier": "BBG000KKFC45",
            "display_name": "Example Index",
            "description": "Example Index Description",
            "provider": "OpenFIGI",
            "metadata_json": {
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
                    "raw_payload": {"figi": "BBG000KKFC45"},
                }
            },
        }
    ]

    with pytest.raises(ValueError, match="marketSector 'Index'"):
        openfigi.upsert_index_from_openfigi_result(
            {
                "unique_identifier": "BBG000BAD",
                "figi": "BBG000BAD",
                "name": "Not An Index",
                "security_market_sector": "Equity",
            }
        )


def test_register_index_from_figi_queries_and_upserts_index(monkeypatch) -> None:
    calls = []
    expected_index = SimpleNamespace(uid=uuid.uuid4())

    def fake_query_by_figi(figi_code, **kwargs):
        calls.append(("query", figi_code, kwargs))
        return {
            "unique_identifier": figi_code,
            "figi": figi_code,
            "name": "Example Index",
            "security_market_sector": "Index",
        }

    def fake_upsert_index_from_openfigi_result(item):
        calls.append(("upsert", item))
        return expected_index

    monkeypatch.setattr(openfigi, "query_by_figi", fake_query_by_figi)
    monkeypatch.setattr(
        openfigi,
        "upsert_index_from_openfigi_result",
        fake_upsert_index_from_openfigi_result,
    )

    assert (
        openfigi.register_index_from_figi(
            "BBG000KKFC45",
            api_key="test-key",
            api_url="https://example.test/openfigi",
        )
        is expected_index
    )
    assert calls == [
        (
            "query",
            "BBG000KKFC45",
            {
                "api_key": "test-key",
                "api_url": "https://example.test/openfigi",
            },
        ),
        (
            "upsert",
            {
                "unique_identifier": "BBG000KKFC45",
                "figi": "BBG000KKFC45",
                "name": "Example Index",
                "security_market_sector": "Index",
            },
        ),
    ]


def test_register_index_future_from_figis_uses_index_and_future_figis(
    monkeypatch,
) -> None:
    underlying_index_uid = uuid.uuid4()
    settlement_asset_uid = uuid.uuid4()
    margin_asset_uid = uuid.uuid4()
    calls = []
    expected_future = SimpleNamespace(uid=uuid.uuid4())

    def fake_register_index_from_figi(figi_code, **kwargs):
        calls.append(("index", figi_code, kwargs))
        return SimpleNamespace(uid=underlying_index_uid)

    def fake_query_by_figi(figi_code, **kwargs):
        calls.append(("future_figi", figi_code, kwargs))
        return {
            "unique_identifier": figi_code,
            "figi": figi_code,
            "name": "Example Future",
            "security_market_sector": "Equity",
            "raw_payload": {"figi": figi_code},
        }

    def fake_future_upsert(**kwargs):
        calls.append(("future_upsert", kwargs))
        return expected_future

    monkeypatch.setattr(openfigi, "register_index_from_figi", fake_register_index_from_figi)
    monkeypatch.setattr(openfigi, "query_by_figi", fake_query_by_figi)
    monkeypatch.setattr("msm.api.derivatives.Future.upsert", fake_future_upsert)

    expires_at = dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC)
    future = openfigi.register_index_future_from_figis(
        "BBG01SWCTHK4",
        underlying_index_figi="BBG000KKFC45",
        settlement_asset_uid=settlement_asset_uid,
        margin_asset_uid=margin_asset_uid,
        kind="EXPIRING",
        quote_unit="INDEX_POINT",
        settlement_model="LINEAR",
        settlement_method="CASH",
        contract_size=Decimal("50"),
        contract_unit="INDEX_POINT",
        expires_at=expires_at,
        settles_at=expires_at,
        metadata={"source": "test"},
        api_key="test-key",
        api_url="https://example.test/openfigi",
    )

    assert future is expected_future
    assert calls == [
        (
            "index",
            "BBG000KKFC45",
            {
                "api_key": "test-key",
                "api_url": "https://example.test/openfigi",
            },
        ),
        (
            "future_figi",
            "BBG01SWCTHK4",
            {
                "api_key": "test-key",
                "api_url": "https://example.test/openfigi",
            },
        ),
        (
            "future_upsert",
            {
                "unique_identifier": "BBG01SWCTHK4",
                "kind": "EXPIRING",
                "underlying_index_uid": underlying_index_uid,
                "quote_unit": "INDEX_POINT",
                "settlement_asset": settlement_asset_uid,
                "margin_asset": margin_asset_uid,
                "settlement_model": "LINEAR",
                "settlement_method": "CASH",
                "contract_size": Decimal("50"),
                "contract_unit": "INDEX_POINT",
                "expires_at": expires_at,
                "settles_at": expires_at,
                "metadata": {
                    "source": "test",
                    "underlying_index_figi": "BBG000KKFC45",
                    "openfigi": {
                        "figi": "BBG01SWCTHK4",
                        "composite": None,
                        "share_class": None,
                        "ticker": None,
                        "name": "Example Future",
                        "exchange_code": None,
                        "security_type": None,
                        "security_type_2": None,
                        "security_market_sector": "Equity",
                        "security_description": None,
                        "unique_id": None,
                        "unique_id_fut_opt": None,
                        "metadata": None,
                        "raw_payload": {"figi": "BBG01SWCTHK4"},
                    },
                },
            },
        ),
    ]
