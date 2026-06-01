from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import ClassVar

from msm_pricing.instruments import Instrument


class ExampleTerms(Instrument):
    expected_asset_type: ClassVar[str] = "example_bond"

    notional: float
    fixed_rate: float
    reference_index_uid: uuid.UUID


def main() -> None:
    asset = SimpleNamespace(uid=uuid.uuid4(), asset_type="example_bond")
    terms = ExampleTerms(
        notional=1_000_000,
        fixed_rate=0.0425,
        reference_index_uid=uuid.uuid4(),
    )
    terms.validate_asset(asset)

    payload = json.loads(terms.serialize_for_backend())

    identity_fields = {"main_sequence_asset_id", "asset_uid", "uid"}
    if identity_fields.intersection(payload["instrument"]):
        raise RuntimeError("Instrument payload unexpectedly contains persistence identity.")

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
