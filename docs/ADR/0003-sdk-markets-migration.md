# 0003. SDK Markets Migration

## Status

Accepted

## Context

Market-domain ORM models, data nodes, instruments, portfolios, repositories, and
services were originally located in the SDK under:

```text
mainsequence/markets
```

The SDK should remain the platform client and project runtime. Market-specific
domain code should live in this dedicated `ms-markets` package.

## Decision

Move the SDK package:

```text
mainsequence-sdk/mainsequence/markets
```

into this repository as:

```text
src/msm
```

Rewrite internal Python imports from `mainsequence.markets.*` to `msm.*`.

Keep existing platform identifiers such as `mainsequence.markets.portfolios`
unchanged where they identify deployed data nodes, metatables, or stable
platform resources rather than Python import paths.

## Consequences

The SDK no longer owns the markets implementation package.

Application code should import market functionality from `msm`.

The `ms-markets` package depends on `mainsequence`, so the SDK should treat
markets as an optional external package rather than importing it as SDK internals.
