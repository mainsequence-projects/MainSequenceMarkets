"""compress discount curve key nodes

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-01 14:18:00.000000

"""

from __future__ import annotations

import base64
import json
import zlib
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_NAME = "ms_markets__discountcurvests"
_KEY_NODES_CODEC_PREFIX = "msm_pricing.key_nodes.zlib+base64.v1:"


def upgrade() -> None:
    """Upgrade schema."""

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"""
            SELECT ctid::text AS row_ctid, key_nodes
            FROM {_TABLE_NAME}
            WHERE key_nodes IS NOT NULL
            """
        )
    ).mappings()
    for row in rows:
        compressed_key_nodes = _compress_key_nodes(row["key_nodes"])
        connection.execute(
            sa.text(
                f"""
                UPDATE {_TABLE_NAME}
                SET key_nodes = to_jsonb(CAST(:compressed_key_nodes AS text))
                WHERE ctid = CAST(:row_ctid AS tid)
                """
            ),
            {
                "compressed_key_nodes": compressed_key_nodes,
                "row_ctid": row["row_ctid"],
            },
        )

    op.alter_column(
        _TABLE_NAME,
        "key_nodes",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using=(
            "CASE "
            "WHEN key_nodes IS NULL THEN NULL "
            "WHEN jsonb_typeof(key_nodes) = 'string' THEN key_nodes #>> '{}' "
            "ELSE key_nodes::text "
            "END"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"""
            SELECT ctid::text AS row_ctid, key_nodes
            FROM {_TABLE_NAME}
            WHERE key_nodes LIKE :codec_prefix
            """
        ),
        {"codec_prefix": f"{_KEY_NODES_CODEC_PREFIX}%"},
    ).mappings()
    for row in rows:
        key_nodes_json = json.dumps(
            _decompress_key_nodes(row["key_nodes"]),
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        connection.execute(
            sa.text(
                f"""
                UPDATE {_TABLE_NAME}
                SET key_nodes = :key_nodes_json
                WHERE ctid = CAST(:row_ctid AS tid)
                """
            ),
            {
                "key_nodes_json": key_nodes_json,
                "row_ctid": row["row_ctid"],
            },
        )

    op.alter_column(
        _TABLE_NAME,
        "key_nodes",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using="key_nodes::jsonb",
    )


def _compress_key_nodes(value) -> str:
    if not isinstance(value, (dict, list)):
        raise ValueError(
            "Cannot compress discount-curve key_nodes because an existing row "
            "is not a JSON object or list."
        )
    json_bytes = json.dumps(
        value,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    compressed_bytes = zlib.compress(json_bytes)
    encoded = base64.b64encode(compressed_bytes).decode("ascii")
    return f"{_KEY_NODES_CODEC_PREFIX}{encoded}"


def _decompress_key_nodes(value: str):
    encoded = value.removeprefix(_KEY_NODES_CODEC_PREFIX)
    compressed_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
    json_bytes = zlib.decompress(compressed_bytes)
    decoded = json.loads(json_bytes.decode("utf-8"))
    if not isinstance(decoded, (dict, list)):
        raise ValueError(
            "Cannot restore discount-curve key_nodes because a compressed row "
            "does not decode to a JSON object or list."
        )
    return decoded
