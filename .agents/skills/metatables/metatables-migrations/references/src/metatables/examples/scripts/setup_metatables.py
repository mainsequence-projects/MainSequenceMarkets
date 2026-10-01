"""Create/migrate tutorial tables on the selected API runtime."""

import argparse
from pathlib import Path


def setup_metatables():
    from metatables.endpoint import api_endpoint_scope, resolve_api_endpoint
    from metatables.runtime import upgrade_application

    with api_endpoint_scope():
        print(f"Preparing tutorial on MetaTables API: {resolve_api_endpoint().url}", flush=True)
        result = upgrade_application('metatables.examples.tutorial.migrations:migration', timeout=120)
        print(f"Tutorial DataSource: {result['data_source_uid']}; revision: {result['revision']} "
              f"({'migrated' if result['migrated'] else 'already current'})", flush=True)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-client", type=Path,
                        help="Use the private connection from the running local API/Admin launcher")
    args = parser.parse_args()
    if args.development_client:
        from metatables.api.app.development_client import configure_development_client

        configure_development_client(args.development_client)
    setup_metatables()


if __name__ == "__main__":
    main()
