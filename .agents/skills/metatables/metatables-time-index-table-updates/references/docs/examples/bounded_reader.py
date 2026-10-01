"""Process an existing time-index table with one typed page in memory."""

from metatables import TimeIndexTableRef


def process_balances(table_uid, start, end, consume):
    reference = TimeIndexTableRef.from_uid(table_uid)
    for batch in reference.iter_batches(
        start_date=start, end_date=end, columns=["balance"], page_size=500,
        max_rows=1_000_000, max_bytes=256 * 1024 * 1024, deadline_seconds=300,
    ):
        consume(batch)
