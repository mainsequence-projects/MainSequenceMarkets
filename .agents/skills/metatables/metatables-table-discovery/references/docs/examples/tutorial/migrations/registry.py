"""The instrument table and three time-index tables belong to this provider."""

from metatables.migrations import build_metatable_model_registry

from ..tables import Asset, Base, DailyClose, DailyReturn, RollingVolatility


def metatable_provider_models():
    return build_metatable_model_registry(
        [Asset, DailyClose, DailyReturn, RollingVolatility], base=Base
    )
