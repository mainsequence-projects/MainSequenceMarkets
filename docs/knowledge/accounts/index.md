# Accounts

The accounts concept owns account identity, account-level holdings, virtual fund
holdings, and assignments between accounts and target portfolios.

## Scope

Accounts answer these questions:

- Which account or virtual fund owns a position?
- Which assets are held at a point in time?
- Which portfolio target should an account follow?
- Which storage contracts represent account and virtual fund holdings?

## Primary Modules

- `msm.data_nodes.accounts`: canonical holdings DataNodes for account and
  virtual fund holdings.
- `msm.models.accounts`: SQLAlchemy account and account assignment models.
- `msm.models.funds`: SQLAlchemy fund model.
- `msm.api.accounts`: Pydantic row APIs for `Account`,
  `AccountModelPortfolio`, `AccountGroup`, and
  `AccountTargetPositionAssignment`.
- `msm.repositories.accounts` and `msm.services.accounts`: MetaTable operation
  builders and service helpers for account records.

## Key Contracts

Account holdings are time-indexed by `time_index` and scoped by account, asset,
and holdings set identifiers. Virtual fund holdings follow the same pattern but
are scoped by fund identifiers.

DataNode inputs should normalize identifiers to stable string values before
publishing. Amount-like values should be normalized before storage so downstream
portfolio and reporting code does not need to guess representation.

Use typed row APIs for account registry records:

```python
from msm.api.accounts import Account

account = Account.upsert(
    unique_identifier="acct-main",
    account_name="Main Account",
    is_paper=True,
)
active_accounts = Account.filter(account_is_active=True)
```

Relationship tables stay explicit. For example,
`AccountTargetPositionAssignment.upsert(...)` owns the binding from an account to
a target-position set; `Account.upsert(...)` does not hide that mutation.

## Extension Notes

Add account registry behavior in `msm.models`, `msm.repositories`, and
`msm.services`. Add time-series holdings behavior in `msm.data_nodes.accounts`. Add
persistence schema changes in `msm.models`, then surface repository or service
operations only when application code needs a stable operation boundary.

## Related Concepts

- [Assets](../assets/index.md)
- [Portfolios](../portfolios/index.md)
- [Repositories](../repositories/index.md)
- [Services](../services/index.md)
