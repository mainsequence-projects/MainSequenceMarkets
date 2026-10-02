"""index formula and custom calculation

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-20 17:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace legacy derived methodologies with strict formula/custom semantics."""

    legacy_definition = op.get_bind().execute(
        sa.text(
            "SELECT uid FROM ms_markets__indexcalculationdefinition "
            "ORDER BY uid LIMIT 1"
        )
    ).first()
    if legacy_definition is not None:
        raise RuntimeError(
            "0015 cannot infer exact source MetaTable UIDs from legacy Index calculation "
            "legs. Remove and republish legacy definitions before upgrading; no compatibility "
            "conversion is provided. First legacy definition uid: "
            f"{legacy_definition.uid}"
        )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cadence_tables = sorted(
        table_name
        for table_name in inspector.get_table_names()
        if table_name.startswith("ms_markets__index_values__t_")
    )

    op.add_column(
        "ms_markets__index",
        sa.Column("calculation_method", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "ms_markets__index",
        sa.Column("value_format", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "ms_markets__index",
        sa.Column("value_suffix", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE ms_markets__index "
            "SET calculation_method = 'custom', value_format = 'decimal'"
        )
    )
    op.alter_column(
        "ms_markets__index",
        "calculation_method",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.alter_column(
        "ms_markets__index",
        "value_format",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.create_check_constraint(
        op.f("ck__ms_markets__index__index_calculation_method_valid"),
        "ms_markets__index",
        "calculation_method IN ('formula', 'custom')",
    )
    op.create_check_constraint(
        op.f("ck__ms_markets__index__index_value_format_valid"),
        "ms_markets__index",
        "value_format IN ('decimal', 'percent')",
    )

    op.drop_table("ms_markets__indexresolvedlegsts")
    op.drop_table("ms_markets__indexcalculationleg")
    op.drop_constraint(
        op.f("fk__ms_markets__indexvaluests__definition_uid__ms_ma_3500b75a57"),
        "ms_markets__indexvaluests",
        type_="foreignkey",
    )
    for table_name in cadence_tables:
        for foreign_key in inspector.get_foreign_keys(table_name):
            if foreign_key.get("constrained_columns") == ["definition_uid"]:
                op.drop_constraint(foreign_key["name"], table_name, type_="foreignkey")
    op.drop_table("ms_markets__indexcalculationdefinition")

    op.create_table(
        "ms_markets__indexformuladefinition",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("index_uid", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("alignment_policy", sa.String(length=16), nullable=False),
        sa.Column("alignment_parameters_json", sa.JSON(), nullable=True),
        sa.Column("missing_data_policy", sa.String(length=16), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "alignment_policy IN ('exact', 'asof')",
            name=op.f(
                "ck__ms_markets__indexformuladefinition__formula_alig_8887da6f81"
            ),
        ),
        sa.CheckConstraint(
            "missing_data_policy IN ('drop', 'fail')",
            name=op.f(
                "ck__ms_markets__indexformuladefinition__formula_miss_d7f6e121c1"
            ),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name=op.f("ck__ms_markets__indexformuladefinition__formula_status_valid"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f(
                "ck__ms_markets__indexformuladefinition__formula_vali_65436db46f"
            ),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f(
                "ck__ms_markets__indexformuladefinition__formula_vers_6b9a2e4d17"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["index_uid"],
            ["ms_markets__index.uid"],
            name=op.f(
                "fk__ms_markets__indexformuladefinition__index_uid__m_13d9e1ae56"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "uid", name=op.f("pk__ms_markets__indexformuladefinition")
        ),
        info={
            "namespace": "mainsequence.markets",
            "identifier": "IndexFormulaDefinition",
            "markets_storage_app": "ms_markets",
        },
    )
    op.create_index(
        op.f("ix__ms_markets__indexformuladefinition__index_uid"),
        "ms_markets__indexformuladefinition",
        ["index_uid"],
        unique=False,
    )
    op.create_index(
        op.f("ix__ms_markets__indexformuladefinition__status"),
        "ms_markets__indexformuladefinition",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix__ms_markets__indexformuladefinition__valid_from"),
        "ms_markets__indexformuladefinition",
        ["valid_from"],
        unique=False,
    )
    op.create_index(
        op.f("uix__ms_markets__indexformuladefinition__index_uid__version"),
        "ms_markets__indexformuladefinition",
        ["index_uid", "version"],
        unique=True,
    )
    op.create_index(
        op.f("uix__ms_markets__indexformuladefinition__index_uid_2e9e563e08"),
        "ms_markets__indexformuladefinition",
        ["index_uid", "definition_hash"],
        unique=True,
    )
    op.create_index(
        op.f("uix__ms_markets__indexformuladefinition__index_uid"),
        "ms_markets__indexformuladefinition",
        ["index_uid"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "ms_markets__indexformulainput",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("definition_uid", sa.Uuid(), nullable=False),
        sa.Column("asset_uid", sa.Uuid(), nullable=True),
        sa.Column("component_index_uid", sa.Uuid(), nullable=True),
        sa.Column("meta_table_uid", sa.Uuid(), nullable=False),
        sa.Column("observable", sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN asset_uid IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN component_index_uid IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name=op.f(
                "ck__ms_markets__indexformulainput__formula_input_sou_276417d9a7"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["asset_uid"],
            ["ms_markets__asset.uid"],
            name=op.f(
                "fk__ms_markets__indexformulainput__asset_uid__ms_mar_be7c95b321"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["component_index_uid"],
            ["ms_markets__index.uid"],
            name=op.f(
                "fk__ms_markets__indexformulainput__component_index_u_80609d9ccb"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["definition_uid"],
            ["ms_markets__indexformuladefinition.uid"],
            name=op.f(
                "fk__ms_markets__indexformulainput__definition_uid__m_029026c1a6"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__ms_markets__indexformulainput")),
        info={
            "namespace": "mainsequence.markets",
            "identifier": "IndexFormulaInput",
            "markets_storage_app": "ms_markets",
        },
    )
    op.create_index(
        op.f("ix__ms_markets__indexformulainput__definition_uid"),
        "ms_markets__indexformulainput",
        ["definition_uid"],
        unique=False,
    )
    op.create_index(
        op.f("ix__ms_markets__indexformulainput__asset_uid"),
        "ms_markets__indexformulainput",
        ["asset_uid"],
        unique=False,
    )
    op.create_index(
        op.f("ix__ms_markets__indexformulainput__component_index_uid"),
        "ms_markets__indexformulainput",
        ["component_index_uid"],
        unique=False,
    )
    op.create_index(
        op.f("ix__ms_markets__indexformulainput__meta_table_uid"),
        "ms_markets__indexformulainput",
        ["meta_table_uid"],
        unique=False,
    )
    op.create_index(
        op.f("uix__ms_markets__indexformulainput__definition_uid_bcfdf0c865"),
        "ms_markets__indexformulainput",
        ["definition_uid", "asset_uid", "observable"],
        unique=True,
        postgresql_where=sa.text("asset_uid IS NOT NULL"),
    )
    op.create_index(
        op.f("uix__ms_markets__indexformulainput__definition_uid_2c392a239a"),
        "ms_markets__indexformulainput",
        ["definition_uid", "component_index_uid", "observable"],
        unique=True,
        postgresql_where=sa.text("component_index_uid IS NOT NULL"),
    )

    op.create_foreign_key(
        op.f("fk__ms_markets__indexvaluests__definition_uid__ms_ma_e41abab9ce"),
        "ms_markets__indexvaluests",
        "ms_markets__indexformuladefinition",
        ["definition_uid"],
        ["uid"],
        ondelete="RESTRICT",
    )
    op.drop_column("ms_markets__indexvaluests", "unit")
    for table_name in cadence_tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        if "definition_uid" in columns:
            op.create_foreign_key(
                None,
                table_name,
                "ms_markets__indexformuladefinition",
                ["definition_uid"],
                ["uid"],
                ondelete="RESTRICT",
            )
        if "unit" in columns:
            op.drop_column(table_name, "unit")


def downgrade() -> None:
    raise RuntimeError(
        "0015 is an intentional hard architecture replacement and has no legacy downgrade"
    )
