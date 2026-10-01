"""Describe an existing relation and register its verified catalog binding."""
from sqlalchemy import Column, Integer, MetaData, String, Table

from metatables import register_external_sqlalchemy_model

positions = Table(
    "external_positions", MetaData(schema="public"),
    Column("position_id", Integer, primary_key=True,
           info={"label": "Position ID", "description": "Stable source-system position identity."}),
    Column("symbol", String(32), nullable=False,
           info={"label": "Symbol", "description": "Instrument symbol of this position."}),
)


def register(data_source_uid: str):
    # The physical relation must already exist with this contract.
    return register_external_sqlalchemy_model(
        positions, data_source_uid=data_source_uid, identifier="positions.external",
        namespace="positions", description="Existing positions supplied by an external producer.",
    )
