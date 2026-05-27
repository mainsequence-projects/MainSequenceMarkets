from __future__ import annotations

from importlib.metadata import version as _package_version

from msm.bootstrap import create_schemas, get_runtime

__version__ = _package_version("ms-markets")


__all__ = [
    "__version__",
    "api",
    "data_nodes",
    "models",
    "portfolios",
    "services",
    "create_schemas",
    "get_runtime",
]
