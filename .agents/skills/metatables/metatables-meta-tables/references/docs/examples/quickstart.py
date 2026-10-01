"""Read and validate an already visible table through the configured API."""
import argparse
import json

from metatables import MetaTable


def inspect_table(uid: str):
    table = MetaTable.get_by_uid(uid)
    validation = table.validate_existing_contract(table_contract=table.table_contract)
    return {"uid": table.uid, "identifier": table.identifier, "validation": validation}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table_uid")
    print(json.dumps(inspect_table(parser.parse_args().table_uid), default=str, indent=2))
