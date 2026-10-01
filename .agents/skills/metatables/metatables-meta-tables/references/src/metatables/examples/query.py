"""Compile bound parameters with database-enforced table grants."""
from sqlalchemy import select

from metatables import MetaTable
from metatables.compiled_sql.v1 import compile_sqlalchemy_statement

from .tables import Account


def account_query(data_source_uid: str, name: str, *, dialect=None):
    statement = select(Account.__table__).where(Account.name == name)
    return compile_sqlalchemy_statement(
        statement, operation="select", dialect=dialect,
        data_source_uid=data_source_uid,
    )


def find_accounts(data_source_uid: str, name: str):
    return MetaTable.execute_operation(account_query(data_source_uid, name))
