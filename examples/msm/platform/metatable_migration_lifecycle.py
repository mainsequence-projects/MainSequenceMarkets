from __future__ import annotations

PROVIDER = "msm_migrations:migration"


def main() -> None:
    print("ms-markets MetaTable migrations use the application-owned MetaTables provider:")
    print(PROVIDER)

    print("\nLocal schema-development command sequence (prints only; executes no DDL):")
    for command in (
        f"metatables --local --json migrations current --provider {PROVIDER}",
        f'metatables --local migrations revision --provider {PROVIDER} -m "describe change"',
        f"metatables --local migrations upgrade --provider {PROVIDER} head",
        f"metatables --local migrations downgrade --provider {PROVIDER} <revision>",
    ):
        print(command)

    print("\nHosted: candidate image -> jobs/migrate_markets.py -> API rollout")
    print(f"The Job calls metatables.upgrade_application({PROVIDER!r}) on every deployment.")
    print("MetaTables >=0.1.31 batches inspections and waits up to 300s for a waking API.")
    print("At head, catalog reconciliation still runs; migrated=False is not a skip signal.")
    print("INFO logs from metatables.migrations.runner report each phase's elapsed time.")
    print("Consumers migrate only their own providers, not the ms-markets provider.")


if __name__ == "__main__":
    main()
