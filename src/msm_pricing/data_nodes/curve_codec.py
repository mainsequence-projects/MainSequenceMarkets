from __future__ import annotations

import base64
import gzip
import json
from collections.abc import Mapping
from typing import Any


def compress_curve_to_string(curve_dict: Mapping[Any, Any]) -> str:
    """Serialize a curve dictionary into the compressed string stored by curve DataNodes."""

    if not isinstance(curve_dict, Mapping) or not curve_dict:
        raise ValueError("Discount curve payload must be a non-empty mapping.")
    json_bytes = json.dumps(curve_dict, separators=(",", ":")).encode("utf-8")
    compressed_bytes = gzip.compress(json_bytes)
    base64_bytes = base64.b64encode(compressed_bytes)
    return base64_bytes.decode("ascii")


def decompress_string_to_curve(b64_string: str) -> dict[Any, Any]:
    """Decode the compressed curve string stored by curve DataNodes."""

    base64_bytes = b64_string.encode("ascii")
    compressed_bytes = base64.b64decode(base64_bytes)
    json_bytes = gzip.decompress(compressed_bytes)
    return json.loads(json_bytes.decode("utf-8"))
