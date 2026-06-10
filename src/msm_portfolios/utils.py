import pandas as pd

from mainsequence import logger as _mainsequence_logger


def get_portfolios_logger():
    _mainsequence_logger.bind(sub_application="portfolios")
    return _mainsequence_logger


logger = get_portfolios_logger()

# Small time delta for precision operations
TIMEDELTA = pd.Timedelta("5ms")
