from __future__ import annotations

from mainsequence.tdag.meta_tables import metatable_configured_tablename

from examples.platform.bootstrap import configure_examples_metatable_namespace

configure_examples_metatable_namespace()

from msm.models import markets_sqlalchemy_models  # noqa: E402


def describe_markets_metatable_models() -> list[dict[str, str]]:
    """Return the SDK-derived platform-managed table names for markets models."""

    rows: list[dict[str, str]] = []
    for model in markets_sqlalchemy_models():
        rows.append(
            {
                "model": model.__name__,
                "identifier": model.metatable_identifier(),
                "schema": str(model.__table__.schema),
                "table_name": model.__table__.name,
                "configured_table_name": metatable_configured_tablename(model),
            }
        )
    return rows


def main() -> None:
    for row in describe_markets_metatable_models():
        print(
            "{model}: {schema}.{table_name} ({identifier})".format(
                **row,
            )
        )


if __name__ == "__main__":
    main()
