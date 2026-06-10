# msm_pricing/instruments/base_instrument.py
import datetime
import inspect
import json
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar, Self

from pydantic import BaseModel, PrivateAttr, model_validator

STALE_INDEX_NAME_FIELDS = frozenset(
    {
        "benchmark_rate_index_name",
        "floating_rate_index_name",
        "float_leg_index_name",
    }
)


class InstrumentModel(BaseModel):
    """Common base for identity-free Pydantic pricing instrument terms."""

    # Keep your existing behavior (QuantLib types, etc.)
    model_config = {"arbitrary_types_allowed": True}

    _valuation_date: datetime.datetime | None = PrivateAttr(default=None)
    _asset_uid: uuid.UUID | None = PrivateAttr(default=None)

    _DEFAULT_REGISTRY: ClassVar[dict[str, type["InstrumentModel"]]] = {}
    expected_asset_type: ClassVar[str | None] = None

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_main_sequence_asset_id(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and "main_sequence_asset_id" in data:
            raise ValueError(
                "main_sequence_asset_id is legacy. Store asset identity on "
                "AssetCurrentPricingDetailsTable.asset_uid, not in instrument terms."
            )
        if isinstance(data, Mapping):
            stale_fields = sorted(STALE_INDEX_NAME_FIELDS.intersection(data))
            if stale_fields:
                fields = ", ".join(stale_fields)
                raise ValueError(
                    f"{fields} are legacy pricing relationships. Persist backend "
                    "IndexTable.uid references with *_index_uid fields instead."
                )
        return data

    def __init_subclass__(cls, **kwargs):
        """Auto-register concrete subclasses for rebuild()."""
        super().__init_subclass__(**kwargs)
        if cls is InstrumentModel:
            return  # don't register the base itself
        # Skip abstract classes (like Bond once we mark it ABC)
        if inspect.isabstract(cls):
            return
        name = cls.__name__
        InstrumentModel._DEFAULT_REGISTRY[name] = cls

    # public read access (still not serialized)
    @property
    def valuation_date(self) -> datetime.datetime | None:
        return self._valuation_date

    # explicit setter method (per your request)
    def set_valuation_date(self, value: datetime.datetime | None) -> None:
        old_value = self._valuation_date
        self._valuation_date = value
        if old_value != value and hasattr(self, "_on_valuation_date_set"):
            self._on_valuation_date_set()

    def attach_to_asset(self, asset: Any, **options: Any) -> Self:
        """Persist this instrument as the current pricing definition for an asset."""

        self.validate_asset(asset)
        from msm_pricing.api.instruments import add_pricing_details

        add_pricing_details(
            asset=asset,
            instrument=self,
            **options,
        )
        self._asset_uid = asset.uid
        return self

    @classmethod
    def load_from_asset(cls, asset: Any, **options: Any) -> Self:
        """Load the concrete current pricing instrument attached to an asset."""

        from msm_pricing.api.instruments import load_instrument_from_asset

        instrument = load_instrument_from_asset(asset, **options)
        if cls is not InstrumentModel and not isinstance(instrument, cls):
            raise TypeError(
                f"Asset {getattr(asset, 'uid', None)} is attached to "
                f"{type(instrument).__name__}, not {cls.__name__}."
            )
        instrument.validate_asset(asset)
        instrument._asset_uid = cls._asset_uid_from_asset(asset)
        return instrument

    def validate_asset(self, asset: Any) -> None:
        """Validate that this instrument can be attached to the provided asset."""

        self.__class__.validate_asset_for_instrument(asset)

    @classmethod
    def validate_asset_for_instrument(cls, asset: Any) -> None:
        asset_uid = cls._asset_uid_from_asset(asset)
        asset_type = getattr(asset, "asset_type", None)
        expected_asset_type = cls.expected_asset_type
        if expected_asset_type is not None and asset_type != expected_asset_type:
            raise ValueError(
                f"{cls.__name__} requires asset_type={expected_asset_type!r}; "
                f"asset {asset_uid} has asset_type={asset_type!r}."
            )

    @staticmethod
    def _asset_uid_from_asset(asset: Any) -> uuid.UUID:
        asset_uid = getattr(asset, "uid", None)
        if asset_uid in (None, ""):
            raise ValueError("Asset must expose a non-empty uid.")
        return uuid.UUID(str(asset_uid))

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self, **json_kwargs: Any) -> str:
        return json.dumps(self.to_json_dict(), default=str, **json_kwargs)

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]):
        data = cls._fix_schedule_calendar_from_top_level(data)
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, payload: str | bytes | dict[str, Any]):
        if isinstance(payload, dict):
            return cls.from_json_dict(payload)
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        return cls.from_json_dict(json.loads(payload))

    def serialize_for_backend(self):
        serialized = {}
        data = self.model_dump_json()
        data = json.loads(data)
        serialized["instrument_type"] = type(self).__name__
        serialized["instrument"] = data

        return json.dumps(serialized)

    @classmethod
    def rebuild(
        cls,
        data: str | dict[str, Any],
        registry: Mapping[str, type["InstrumentModel"]] | None = None,
    ) -> "InstrumentModel":
        """
        Rebuild a single instrument from its wire format.

        Accepts either:
          - a dict: {"instrument_type": "FixedRateBond", "instrument": {...}}
          - a JSON string of the same shape

        Optional `registry` maps instrument_type -> InstrumentModel subclass.
        Falls back to InstrumentModel._DEFAULT_REGISTRY.
        """
        import msm_pricing as msp

        # Parse JSON if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as err:
                # Keep the original cause so stacktraces show *why* parsing failed
                raise ValueError("Invalid JSON for instrument.") from err

        if not isinstance(data, dict):
            raise ValueError("Instrument payload must be dict or JSON string.")

        cls._reject_legacy_main_sequence_asset_id(data)
        t = data.get("instrument_type")
        payload = data.get("instrument", {})
        if not t or not isinstance(payload, dict):
            raise ValueError("Expected {'instrument_type': <str>, 'instrument': <dict>}.")

        # Merge registries (explicit registry overrides defaults)
        effective_registry: dict[str, type[InstrumentModel]] = dict(cls._DEFAULT_REGISTRY)
        if registry:
            effective_registry.update(registry)

        target_cls = effective_registry.get(t)
        if target_cls is None:
            target_cls = getattr(msp, t, None)
        if target_cls is None:
            raise ValueError(f"Unknown instrument type: {t}")
        if not hasattr(target_cls, "from_json"):
            raise TypeError(f"Instrument type {t} is not JSON-rebuildable (missing from_json).")

        return target_cls.from_json(payload)

    @staticmethod
    def _fix_schedule_calendar_from_top_level(data: dict[str, Any]) -> dict[str, Any]:
        try:
            from .json_codec import _fix_schedule_calendar_from_top_level
        except ModuleNotFoundError as exc:
            if exc.name == "QuantLib":
                return data
            raise
        return _fix_schedule_calendar_from_top_level(data)
