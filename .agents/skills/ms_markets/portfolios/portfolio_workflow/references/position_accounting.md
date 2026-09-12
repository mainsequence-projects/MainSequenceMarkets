# Position-Aware Accounting Maintenance

Use this reference only for `msm_portfolios` position accounting, lifecycle cash
flows, accounting valuation, deterministic restart, or ledger-derived projections.

## Ownership

- `PortfolioEngine` is the `TimeIndexTableUpdater` orchestration and publication
  boundary.
- A Portfolio is a backtest model with no Account, custody, broker execution, or
  actual account state.
- The configured signal and `RebalanceStrategy` are the only source of simulated
  Portfolio executions. Their execution facts are an internal typed boundary to
  accounting, never an external input lane.
- `PortfolioAccounting` is a pure deterministic in-memory reducer and must not
  become a MetaTable, updater, persistence client, or user extension point.
- Directly injected `LifecycleEventModel` instances own lifecycle economics.
- `PositionValuationModel` owns valuation of the complete accounting state from
  explicit observations.
- `PortfolioEventLedgerStorage` is the only authoritative persisted output.
- Portfolio state, cash flows, weights, NAV/returns, and analytics are
  deterministic read projections from the ledger.
- Core `msm` continues to own `PortfolioTable` and `AssetTable` identity.
- The architecture requires no new `mainsequence-sdk` feature. Never report an
  accounting implementation task as SDK-blocked without a separately reproduced
  SDK defect.

## Mode Boundary And Compatibility

- `PortfolioBuildConfiguration.accounting_configuration` is optional.
- Omitted and explicit `None` must preserve the legacy serialized payload,
  configuration hash, dependency graph, output identity, and stored history.
- Enabled accounting is hash-bearing and creates a distinct history.
- `PortfoliosDataNode` must reject enabled accounting; it must not silently
  downgrade, mix histories, or fabricate accounting state from weights.
- Do not restore the rejected `unique_identifier` source-field fallback.
  Accounting Asset inputs use `asset_identifier` and persisted FKs target
  `AssetTable.unique_identifier`.

## Input Contracts

Keep source grains truthful and time-first:

```text
signals:               time_index, signal_uid, asset_identifier
execution observations: time_index + source dimensions
valuations:             time_index, asset_identifier
FX:                     time_index, base_asset_identifier, quote_asset_identifier
dividends:              time_index, source_event_identifier, source_revision
```

Require stable source identities and revisions. Use economic time for
`time_index` and availability time for `observed_at`. In `as_known` mode, reject
an observation that became available after the event being calculated. Missing
or stale price/FX/terms/eligibility input is an error, never zero or a fallback.

Internal simulated execution facts must retain signed quantity, unit, execution
price, quote Asset, source revisions, terms version, settlement legs, and costs.
They are generated from the post-lifecycle/pre-execution accounting state. Do
not accept actual account or broker fills as Portfolio inputs.

Use `TargetWeightExecutionModel` plus one `InstrumentExecutionSpec` per
economically required Asset for the built-in position-aware sizing path. An
unchanged zero target needs neither terms nor a mark; entries and exits do. Each
spec declares target measure,
quantity unit, contract multiplier, quantity step, quote Asset, settlement style,
and terms version. Use `settlement_style="cash"` for trade consideration and
`settlement_style="variation_margin"` when changing contract quantity must not
deduct full notional. Put fill-time fees in strategy-owned
`ExecutionCostModel`s; keep funding, borrow, interest, dividends, coupons, and
other holding-period economics in lifecycle models.

`MarketPriceValuationModel` requires explicit direct FX from each foreign Asset
to the portfolio valuation Asset. Do not infer inverse pairs. Value positions,
cash, and obligations as disjoint components exactly once.

## Event And Ledger Invariants

An `EventBatch` is flat and columnar, with offsets delimiting variable-length
events. Every complete event has one envelope, one or more typed records, and
exactly one `valuation_summary`.

The authoritative grain is:

```text
(time_index, portfolio_identifier, event_identifier,
 event_revision, record_identifier)
```

Preserve these invariants:

- stable economic event identity independent of insertion order;
- deterministic event revision from model/source/input-state revisions;
- contiguous event and record ordering;
- record count and digest agreement across the whole event group;
- one input/output state-identifier chain;
- signed deltas with explicit quantity units and Asset identities;
- event-level NAV and recognized P&L only on the summary record;
- exact retry idempotency; and
- explicit zero/closed state rows in projections.

Recognition and settlement are different transitions. A recognized receivable
survives sale of its originating position. Settlement exchanges obligation for
cash and must not recognize the income again. A post-cutoff buyer must not gain
the prior holder's entitlement.

## Extension Boundary

The supported `LifecycleEventModel` override surface is limited to:

```text
declared_dependencies
required_input_contracts
dependency_window
alignment_contracts
lifecycle_state_contract
select_event_candidates
vectorization_keys
build_event_batch
```

Use `PositionCashFlowModel.calculate_cash_deltas` only for the narrower immediate
cash-posting case. Use full `LifecycleEventModel` event records for obligations,
position changes, deliverables, resets, or model-owned state.

Custom models must be module-level and importable, directly injected, and
canonically serialized with class path, model/configuration versions, economic
configuration, ordering priority, and dependency identities. Do not add a
string registry, implicit built-in fallback, instrument-family switch in the
engine, or user-overridable reducer/publication hook.

Models are pure. They may use only declared inputs, immutable state, explicit
terms, and supplied valuation context. They must not perform hidden reads, use
wall-clock time, mutate engine state, or write storage.

## Vectorization

Sequential processing is valid across economically dependent timestamps and
causal groups. Within those boundaries, group compatible rows and invoke model
kernels once per vectorization signature. Do not use per-row model dispatch when
rows share a kernel.

Different source grains do not prevent batching. Resolve them through declared
alignment policies, then use mapping arrays and segmented reductions. Avoid an
unbounded Cartesian expansion or unbounded forward fill. Keep event records flat
with offset arrays for ragged multi-leg events.

Maintain the readable reference reducer as the correctness oracle. An optimized
implementation must consume the same batches and prove identical ledger records
and final state before any performance claim.

## Restart, Corrections, And Projections

Restart only from the complete active ledger or a snapshot whose
`ledger_state_identifier` is verified against it. Validate event digests, record
counts, opening configuration, sequence continuity, and the state chain.

Exact retries may produce no new rows. A changed or deleted source revision must
never be applied on top of old state. Until correction-tail replay is complete,
fail explicitly. Correction implementation must find the earliest affected
event, replay that portfolio's tail, append superseding/cancellation revisions,
and rebuild only that portfolio's projection tail.

Projection publishers consume the ledger and explicit valuation dependencies.
They may fail or lag without changing ledger truth. Every projection row carries
the ledger-state identity it represents; consumers must reject mismatched
projection revisions.

## Documentation And Examples

Keep these surfaces aligned with code changes:

- `docs/ADR/0042-position-cash-flow-portfolio-accounting.md`
- `docs/knowledge/msm_portfolios/portfolios/accounting.md`
- `docs/knowledge/msm_portfolios/portfolios/index.md`
- `docs/tutorial/04-portfolios.md`
- `CHANGELOG.md`
- `examples/msm_portfolios/portfolio_cashflows_and_fx_valuation_example.py`
- `examples/msm_portfolios/portfolio_custom_cashflow_model_example.py`
- `examples/msm_portfolios/portfolio_perpetual_funding_example.py`

Document implemented behavior separately from pending `msm_portfolios` work.
Never describe a generated-but-unapplied migration as an SDK blocker; applying it
is a deployment action.
