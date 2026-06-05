import pandas as pd

from mainsequence.logconf import logger as _mainsequence_logger


def get_vfb_logger():
    # If the logger doesn't have any handlers, create it using the custom function
    _mainsequence_logger.bind(sub_application="portfolios")
    return _mainsequence_logger


logger = get_vfb_logger()

# Small time delta for precision operations
TIMEDELTA = pd.Timedelta("5ms")
