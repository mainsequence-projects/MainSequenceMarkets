"""Read an existing output without constructing or running its producer."""
from datetime import datetime

from metatables import TimeIndexTableRef


def balances(table_uid: str, account_uid: str, start: datetime, end: datetime):
    reference = TimeIndexTableRef.from_uid(table_uid)
    return reference.get_df_between_dates(
        start_date=start, end_date=end, dimension_filters={"account_uid": [account_uid]},
        columns=["balance"],
    )
