from __future__ import annotations

from mainsequence.meta_tables import POSTGRES_IDENTIFIER_MAX_LENGTH

from msm.schema_names import (
    bounded_identifier,
    parse_schema_table_name,
    schema_foreign_key_name,
    schema_index_name,
    schema_table_name,
)


def test_parse_schema_table_name_preserves_app_concept_and_suffix() -> None:
    table_name = schema_table_name(
        "sample_app",
        "Account",
        suffix="mainsequence.examples",
    )

    parsed = parse_schema_table_name(table_name)

    assert table_name == "sample_app__account__mainsequence_examples"
    assert parsed.app == "sample_app"
    assert parsed.concept == "account"
    assert parsed.suffix == "mainsequence_examples"


def test_bounded_identifier_preserves_table_name_separator_when_possible() -> None:
    name = bounded_identifier("ix", "sample_app__account", "account_uid")

    assert name == "ix__sample_app__account__account_uid"
    assert len(name) <= POSTGRES_IDENTIFIER_MAX_LENGTH


def test_bounded_identifier_hashes_overlong_names_deterministically() -> None:
    name = bounded_identifier(
        "fk",
        "sample_app__assetcurrentpricingdetails__mainsequence_examples",
        "asset_uid",
        "sample_app__asset__mainsequence_examples",
        "uid",
    )

    assert name == bounded_identifier(
        "fk",
        "sample_app__assetcurrentpricingdetails__mainsequence_examples",
        "asset_uid",
        "sample_app__asset__mainsequence_examples",
        "uid",
    )
    assert name.startswith("fk__")
    assert len(name) <= POSTGRES_IDENTIFIER_MAX_LENGTH


def test_index_names_include_all_columns_and_unique_flag() -> None:
    single_column = schema_index_name(
        "sample_app__accountholdingsset__mainsequence_examples",
        ["account_uid"],
    )
    composite_unique = schema_index_name(
        "sample_app__accountholdingsset__mainsequence_examples",
        ["account_uid", "time_index"],
        unique=True,
    )

    assert single_column != composite_unique
    assert single_column.startswith("ix__")
    assert composite_unique.startswith("uix__")
    assert len(single_column) <= POSTGRES_IDENTIFIER_MAX_LENGTH
    assert len(composite_unique) <= POSTGRES_IDENTIFIER_MAX_LENGTH


def test_fk_name_includes_source_columns_target_table_and_target_columns() -> None:
    name = schema_foreign_key_name(
        "sample_app__assetcurrentpricingdetails__mainsequence_examples",
        ["asset_uid"],
        "sample_app__asset__mainsequence_examples",
        ["uid"],
    )

    different_target_column = schema_foreign_key_name(
        "sample_app__assetcurrentpricingdetails__mainsequence_examples",
        ["asset_uid"],
        "sample_app__asset__mainsequence_examples",
        ["unique_identifier"],
    )

    assert name != different_target_column
    assert name.startswith("fk__")
    assert len(name) <= POSTGRES_IDENTIFIER_MAX_LENGTH
