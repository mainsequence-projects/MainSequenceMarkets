# Repositories

The repositories concept owns compiled database operations for market-domain
models. It provides a stable boundary between application services and
MetaTable-backed persistence.

## Scope

Repositories answer these questions:

- How is a market-domain model created, searched, updated, or deleted?
- Which context is needed to compile and execute a database operation?
- Which queries should be reused by services or application code?
- Which operations should stay close to SQLAlchemy instead of client API models?

## Primary Modules

- `msm.repositories.base`: repository context, statement compilation, and
  operation execution helpers.
- `msm.repositories.crud`: generic CRUD builders and execution helpers.
- `msm.repositories.accounts`: account-specific repository operations.
- `msm.repositories.funds`: fund operations and fund lookup by account or
  portfolio.
- `msm.repositories.portfolios`: portfolio operations.

## Key Contracts

Repositories should return operation payloads or dictionaries that application
code can use without reaching into SQLAlchemy internals. They should keep query
construction explicit and testable.

Repository functions should accept a `MarketsRepositoryContext` when they need
platform metadata or execution settings.

## Extension Notes

Add generic behavior in `crud` only when it applies across models. Add
model-specific query behavior in a dedicated repository module. Promote
repository calls into `services` when application workflows need orchestration
or a simpler public API.

## Related Concepts

- [Models](../models/index.md)
- [Services](../services/index.md)
- [Accounts](../accounts/index.md)
- [Portfolios](../portfolios/index.md)
