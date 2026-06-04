from __future__ import annotations

PROVIDER = "migrations:migration"


def main() -> None:
    print("ms-markets MetaTable migrations use the SDK Alembic provider:")
    print(PROVIDER)

    print("\nAdmin command sequence:")
    for command in (
        f"mainsequence migrations current --provider {PROVIDER} --json",
        f'mainsequence migrations revision --provider {PROVIDER} --autogenerate -m "describe change"',
        f"mainsequence migrations upgrade --provider {PROVIDER} head",
        f"mainsequence migrations downgrade --provider {PROVIDER} <revision>",
    ):
        print(command)


if __name__ == "__main__":
    main()
