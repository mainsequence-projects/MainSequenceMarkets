"""Recognize the retired 0017 head as the schema equivalent of the 0018 baseline.

This is an anchor, not a replay of the retired 0001-0017 DDL. The original
0017 tables and 0018 tables have identical columns except ten unbounded
identifiers. Revision 0020 checks the complete column baseline, bounds those
identifiers only after checking every value, and merges both histories.

0018 and 0019 stay byte-for-byte unchanged. A fresh database still runs 0018;
one already at 0017 skips that table-creation revision. Both must reach 0020.
"""

revision: str = "0017"
down_revision: str = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """The physical schema already exists; 0020 performs the compatibility check."""


def downgrade() -> None:
    raise RuntimeError("The legacy schema anchor is forward-only; use a new migration.")
