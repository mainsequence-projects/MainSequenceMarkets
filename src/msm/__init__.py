from __future__ import annotations

from msm.__about__ import __version__


def start(*args, **kwargs):
    from msm.bootstrap import start as _start

    return _start(*args, **kwargs)


__all__ = [
    "__version__",
    "data_nodes",
    "models",
    "portfolios",
    "pricing",
    "services",
    "start",
]
