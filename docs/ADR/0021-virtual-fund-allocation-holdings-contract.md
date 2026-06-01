# 0021. Virtual Fund Allocation Holdings Contract

## Status

Proposed

## Context

`msm_portfolios` currently models virtual funds as `FundTable` rows plus
`VirtualFundHoldings` / `FundHoldingsStorage`. That is too loose for the domain.
A virtual fund should not look like an independent custody account. A virtual
fund is an allocation layer over a real account's holdings, targeted at a
portfolio.

The intended workflow is:

1. A user has an `Account`.
2. The account has real asset holdings.
3. The user wants part of those holdings to track a `Portfolio`.
4. The user creates a `VirtualFund`.
5. The virtual fund has holdings-like rows, but those rows are allocations from
   one account holdings set, not independent custody.
6. Because account systems can only hold assets, the virtual fund can optionally
   create a one-to-one `VirtualFundAsset` proxy.

This ADR extends ADR 0019's package boundary. It also changes the shared base
holdings contract in core `msm` accounts because account holdings and
virtual-fund holdings must use the same side/quantity semantics.

The latest Main Sequence SDK documentation describes Virtual Fund Builder as the
portfolio-construction layer over DataNodes. VFB consumes data, signals,
rebalance logic, and prices to produce portfolio time series. That supports this
split: VFB builds portfolio outputs, while `msm_portfolios` virtual funds bind
those portfolio outputs to account-owned holdings allocations.

## Decision

Introduce a stricter virtual-fund allocation model.

Virtual funds are not custody accounts. They allocate from a concrete account
holdings set. The platform should be able to answer:

- which account holdings set funded this virtual-fund holdings observation;
- which virtual funds allocated from the same source holdings set;
- whether virtual-fund allocations over-allocate any source asset;
- whether each allocation is long or short without using negative quantities.

### Base Holdings Direction Contract

The shared holdings contract must add a `direction` field:

```text
+------------+------------------------------------------------------------+
| field      | rule                                                       |
+------------+------------------------------------------------------------+
| quantity   | positive magnitude, never negative                         |
| direction  | required side: 1 for long, -1 for short                    |
+------------+------------------------------------------------------------+
```

The signed position is derived:

```text
signed_quantity = direction * quantity
```

This applies to core account holdings and to virtual-fund allocation holdings.
The implementation must update the shared holdings builder/validator used by
`AccountHoldingsStorage` and virtual-fund holdings storage.

Do not allow negative `quantity`. Negative quantities make the side ambiguous
and create invalid combinations such as `quantity=-10, direction=-1`.

The initial model keeps `direction` as a required record column, not part of the
canonical holdings index. The holdings index remains one net position per owner,
timestamp, and asset. If later workflows need simultaneous long and short lots
for the same owner/asset/timestamp, that should be a separate lot-level ADR.

### Portfolio Construction And Virtual Fund Allocation Relationships

```text
Virtual Fund Builder / portfolio construction produces portfolio artifacts.
It does not own virtual-fund identity and it does not connect directly to
virtual-fund allocation rows.

+------------------+       +------------------+       +------------------+
| Price DataNodes  |       | Signal DataNodes |       | Rebalance Logic  |
+--------+---------+       +--------+---------+       +--------+---------+
         \                          |                          /
          \                         |                         /
           v                        v                        v
        +---------------------------------------------------------+
        | Portfolio construction / VFB                            |
        | - computes signal weights, portfolio weights, values    |
        | - writes portfolio DataNode outputs                     |
        +---------------------------+-----------------------------+
                                    |
                                    v
+-------------------------+   +-------------------------+   +-------------------------+
| SignalWeights           |   | PortfolioWeights        |   | PortfoliosDataNode      |
| DataNode                |   | DataNode                |   | DataNode                |
+------------+------------+   +------------+------------+   +------------+------------+
             |                             |                             |
             v                             v                             v
+-------------------------+   +-------------------------+   +-------------------------+
| SignalWeightsStorage    |   | PortfolioWeightsStorage |   | PortfoliosStorage       |
| PlatformTimeIndexMeta   |   | PlatformTimeIndexMeta   |   | PlatformTimeIndexMeta   |
+------------+------------+   +------------+------------+   +------------+------------+
             |                             |                             |
             | storage UID                 | storage UID                 | storage UID
             +-----------------------------+-----------------------------+
                                           |
                                           v
        +---------------------------------------------------------+
        | PortfolioTable                                          |
        | - portfolio identity                                    |
        | - signal_weights_data_node_uid                          |
        | - portfolio_weights_data_node_uid                       |
        | - portfolio_data_node_uid                               |
        | - optional portfolio_index_uid -> IndexTable.uid        |
        +---------------------------------------------------------+
```

Virtual-fund allocation is a separate relationship over account holdings and a
target portfolio:

```text
+---------------------+        target_portfolio_uid        +---------------------+
| PortfolioTable      |<-----------------------------------| VirtualFundTable    |
| portfolio identity  |                                    | allocation identity |
+---------------------+                                    | account_uid         |
                                                           +----------+----------+
                                                                      |
                                                                      | account_uid
                                                                      v
+---------------------+        account_uid                +---------------------+
| AccountTable        |<-----------------------------------| AccountHoldingsSet |
| custody account     |                                    | source snapshot    |
+---------------------+                                    +----------+----------+
                                                                      |
                                                                      | source_account_holdings_set_uid
                                                                      v
                                                           +-----------------------------+
                                                           | VirtualFundHoldingsSetTable |
                                                           | allocation set identity     |
                                                           +-------------+---------------+
                                                                         |
                                                                         v
                                                           +-----------------------------+
                                                           | VirtualFundHoldingsStorage  |
                                                           | allocated_quantity          |
                                                           | direction                   |
                                                           | unique_identifier -> Asset  |
                                                           +-----------------------------+
```

### Source Account Holdings Sets

The current loose `holdings_set_uid` UUID is not enough to enforce allocation
lineage. Account holdings need a real set identity:

```text
+-------------------------------+
| AccountHoldingsSetTable       |
|-------------------------------|
| uid PK                        |
| account_uid FK -> Account     |
| time_index                    |
| source_data_node_uid nullable |
+-------------------------------+
```

`AccountHoldingsStorage.holdings_set_uid` should become a foreign key to
`AccountHoldingsSetTable.uid`.

An account holdings set is the source snapshot. It can fund multiple virtual
fund holdings sets:

```text
AccountHoldingsSetTable 1 ---- 0..N VirtualFundHoldingsSetTable
```

It must not be modeled as one-to-one. One account snapshot can allocate, for
example, 6 BTC to one virtual fund and 4 BTC to another.

### Virtual Fund Identity

Rename the current generic fund language to virtual-fund language:

```text
FundTable -> VirtualFundTable
Fund -> VirtualFund
FundHoldingsStorage -> VirtualFundHoldingsStorage
```

Do not add compatibility shims unless a later explicit compatibility decision
requires them.

Target table:

```text
+-------------------------------+
| VirtualFundTable              |
|-------------------------------|
| uid PK                        |
| unique_identifier unique      |
| account_uid FK -> Account     |
| target_portfolio_uid FK       |
| virtual_fund_asset_uid FK     |
+-------------------------------+
```

Remove generic workflow fields from the core identity table unless a later ADR
defines them as first-class domain concepts:

```text
requires_nav_adjustment
metadata_json
```

### VirtualFundAsset Proxy

Accounts hold assets. A virtual fund that needs to be visible to account-facing
systems should have a one-to-one asset proxy:

```text
+-------------------------------+      +-------------------------------+
| VirtualFundTable              |      | VirtualFundAssetDetailsTable  |
|-------------------------------|      |-------------------------------|
| uid PK                        |<-----| virtual_fund_uid unique FK    |
| virtual_fund_asset_uid FK ----+----->| asset_uid PK/FK -> AssetTable |
+-------------------------------+      +-------------------------------+
```

Rules:

- the proxy asset must use asset type `virtual_fund`;
- one virtual fund has at most one proxy asset;
- one proxy asset points to exactly one virtual fund;
- the proxy asset is an account-facing handle, not the source of underlying
  allocations.

### Virtual Fund Holdings Sets

Virtual-fund holdings should be grouped by a real set table:

```text
+----------------------------------------------+
| VirtualFundHoldingsSetTable                  |
|----------------------------------------------|
| uid PK                                       |
| virtual_fund_uid FK -> VirtualFundTable.uid  |
| source_account_holdings_set_uid FK           |
| time_index                                   |
+----------------------------------------------+
```

The practical uniqueness rule is:

```text
unique(virtual_fund_uid, source_account_holdings_set_uid)
```

This states that one virtual fund can publish one allocation view from one source
account holdings set.

### Virtual Fund Holdings Storage

Virtual-fund holdings storage should be explicit that it stores allocations:

```text
+------------------------------------------------+
| VirtualFundHoldingsStorage                     |
|------------------------------------------------|
| time_index                                     |
| virtual_fund_uid                               |
| unique_identifier                              |
| virtual_fund_holdings_set_uid                  |
| source_account_holdings_set_uid                |
| allocated_quantity                             |
| direction                                      |
| target_trade_time nullable                     |
| extra_details nullable                         |
+------------------------------------------------+
```

The row grain is:

```text
(time_index, virtual_fund_uid, unique_identifier)
```

`quantity` should be renamed to `allocated_quantity` for virtual-fund storage so
callers do not confuse allocated exposure with custody.

`target_weight` should not be a core field in virtual-fund holdings storage. The
target comes from the portfolio weights DataNode. If a workflow copies target
weights into allocation rows for diagnostics, it should do that in
`extra_details` or through a separate derived-output model.

### Allocation Bound

Before inserting or publishing virtual-fund allocations, the service must verify
the source holdings set. For each source holdings set, asset, and direction:

```text
sum(existing allocated_quantity)
+ sum(new allocated_quantity)
<= source account holdings quantity
```

Expanded key:

```text
(
  source_account_holdings_set_uid,
  unique_identifier,
  direction,
)
```

Example:

```text
Account source holding:
  unique_identifier = BTC
  quantity = 10
  direction = -1

Allowed allocations:
  VirtualFund A: allocated_quantity = 6, direction = -1
  VirtualFund B: allocated_quantity = 4, direction = -1

Rejected allocation:
  VirtualFund C: allocated_quantity = 1, direction = -1
```

The same source short position cannot fund a long allocation. The allocation key
includes `direction`, so a short BTC holding only funds short BTC allocations.

### User-Facing Workflow

The public API should guide users through an allocation workflow instead of
letting them publish arbitrary virtual-fund holdings:

```python
virtual_fund = VirtualFund.upsert(...)
account_holdings_set = AccountHoldingsSet.upsert(...)
virtual_fund.allocate_from_account_holdings_set(
    source_account_holdings_set_uid=account_holdings_set.uid,
    allocations=[
        {
            "unique_identifier": "BTC",
            "allocated_quantity": 6,
            "direction": -1,
        },
    ],
)
```

The lower-level DataNode remains the publishing mechanism, but the normal
user-facing helper must enforce the allocation bound before writing.

## Implementation Tasks

### Stage 1: Account Holdings Base Contract

- [ ] Add `direction` to the shared holdings builder and validator.
- [ ] Add `direction` to `AccountHoldingsStorage` with allowed values `1` and
  `-1`.
- [ ] Enforce positive `quantity` in account holdings.
- [ ] Add `AccountHoldingsSetTable`.
- [ ] Make `AccountHoldingsStorage.holdings_set_uid` reference
  `AccountHoldingsSetTable.uid`.
- [ ] Update account docs, examples, and tests to show positive quantity plus
  direction.

### Stage 2: Virtual Fund Identity

- [ ] Rename `FundTable` to `VirtualFundTable`.
- [ ] Rename public `Fund` API to `VirtualFund`.
- [ ] Remove generic `requires_nav_adjustment` and `metadata_json` fields unless
  another ADR defines them as first-class virtual-fund concepts.
- [ ] Add `VirtualFundAssetDetailsTable` and the `virtual_fund` asset type
  workflow.
- [ ] Add the `VirtualFundAsset` public API helper.

### Stage 3: Allocation Sets And Storage

- [ ] Add `VirtualFundHoldingsSetTable`.
- [ ] Rename `FundHoldingsStorage` to `VirtualFundHoldingsStorage`.
- [ ] Replace `quantity` with `allocated_quantity` in virtual-fund holdings
  storage.
- [ ] Add `direction` to virtual-fund holdings storage.
- [ ] Remove `target_weight` from the core virtual-fund holdings storage
  contract.
- [ ] Add source account holdings set foreign keys.

### Stage 4: Allocation API And Validation

- [ ] Add a typed allocation helper that writes virtual-fund allocations from an
  account holdings set.
- [ ] Query existing allocations from the same source holdings set before
  writing.
- [ ] Enforce the per-asset, per-direction allocation bound.
- [ ] Log rejected allocations with source set, virtual fund, asset, direction,
  source quantity, existing allocated quantity, and requested quantity.

### Stage 5: Documentation, Examples, And Skills

- [ ] Update `docs/knowledge/msm/accounts/index.md` for the new direction
  contract.
- [ ] Update `docs/knowledge/msm_portfolios/virtualfunds/index.md` with the
  allocation model and proxy asset diagram.
- [ ] Add one `examples/msm_portfolios` workflow that creates an account
  holdings set, allocates from it into a virtual fund, and creates the
  `VirtualFundAsset` proxy.
- [ ] Update packaged ms-markets account and portfolio skills so agents do not
  reintroduce negative quantities or independent virtual-fund holdings.
- [ ] Update changelog and tutorial references.

### Stage 6: Tests

- [ ] Add tests for positive quantity and valid direction in account holdings.
- [ ] Add tests for `AccountHoldingsSetTable` FK wiring.
- [ ] Add tests for virtual-fund proxy asset one-to-one constraints.
- [ ] Add tests for allocation bounds across multiple virtual funds sharing one
  account holdings set.
- [ ] Add tests proving short holdings allocate only to short virtual-fund
  allocations.

## Consequences

This makes virtual funds materially safer. The library can prevent a virtual
fund from claiming more exposure than the source account owns, and it can do
that for long and short holdings with the same rule.

The cost is a schema migration across both core account holdings and
`msm_portfolios`. This is not only a portfolio change. Account holdings must gain
direction and holdings-set identity first, otherwise virtual-fund allocation
validation has no reliable source snapshot to reference.

The public API becomes more opinionated. Users should allocate from an account
holdings set through a typed helper rather than constructing arbitrary
virtual-fund holdings frames by hand. That is the right tradeoff because
virtual-fund holdings are not independent holdings.
