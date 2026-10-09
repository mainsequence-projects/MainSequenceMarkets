import pandas as pd

from mainsequence import logger as _mainsequence_logger


def get_portfolios_logger():
    return _mainsequence_logger.bind(sub_application="portfolios")


logger = get_portfolios_logger()

# Small time delta for precision operations
TIMEDELTA = pd.Timedelta("5ms")
