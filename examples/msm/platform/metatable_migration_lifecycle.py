from __future__ import annotations

PROVIDER = "msm_migrations:migration"


def main() -> None:
    print("ms-markets MetaTable migrations use the application-owned MetaTables provider:")
    print(PROVIDER)

    print("\nAdmin command sequence:")
    for command in (
        f"metatables --json migrations current --provider {PROVIDER}",
        f'metatables migrations revision --provider {PROVIDER} -m "describe change"',
        f"metatables --local migrations upgrade --provider {PROVIDER} head",
        f"metatables --local migrations downgrade --provider {PROVIDER} <revision>",
    ):
        print(command)


if __name__ == "__main__":
    main()
