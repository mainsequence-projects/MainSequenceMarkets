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
    ):
        print(command)

    print("\nFresh, legacy 0017, development 0018 and 0019 all upgrade to head 0020.")
    print("0018/0019 stay unchanged; 0020 checks all 62 table column contracts.")
    print("Legacy PostgreSQL limits change only if all identifiers fit 255 characters.")
    print("Affected tables are locked; row counts and checksums must remain unchanged.")
    print("Extra tables/columns remain intact. No reset, stamp, or downgrade is needed.")
    print("The compatibility anchor and merge are forward-only; use new repairs.")

    print("\nHosted: candidate image -> jobs/migrate_markets.py -> API rollout")
    print(f"The Job calls metatables.upgrade_application({PROVIDER!r}) on every deployment.")
    print("MetaTables >=0.1.33 batches inspections; the Job explicitly allows 300s to wake.")
    print("It uses api_endpoint_scope(discovery_timeout=300); failures still stop rollout.")
    print("At head, catalog reconciliation still runs; migrated=False is not a skip signal.")
    print("Changed non-empty authored metadata refreshes without a new Alembic revision.")
    print("Empty metadata preserves existing values; equal-valued reruns avoid catalog writes.")
    print("Metadata finalization also requires the matching shared MetaTables API update.")
    print("INFO logs from metatables.migrations.runner report each phase's elapsed time.")
    print("Consumers migrate only their own providers, not the ms-markets provider.")


if __name__ == "__main__":
    main()
