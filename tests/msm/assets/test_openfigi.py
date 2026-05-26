from __future__ import annotations

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
