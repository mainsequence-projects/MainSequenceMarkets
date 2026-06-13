# MainSequenceMarkets refactor review

Date: 2026-05-31

Reviewed project:
`/Users/jose/mainsequence-dev/main-sequence-workbench/projects/mainsequencemarkets-1d0530c0-65d1-4db0-856b-dc29d8260a09`

SDK baseline used for validation:
`/Users/jose/code/MainSequenceClientSide/mainsequence-sdk`, package version `mainsequence==4.1.5`.

## Verdict

The refactor is directionally aligned with the latest SDK architecture: it moves DataNode storage declarations into SDK-style `PlatformTimeIndexMetaTable` SQLAlchemy classes, derives storage schema from SQLAlchemy metadata instead of hand-maintained contracts, and keeps the runtime DataNode classes using SDK `DataNode` / `APIDataNode` construction.

It is not ready to accept unchanged. There are three blocking alignment issues with the SDK contract:

1. Catalog and existing-platform attach paths do not bind `PlatformTimeIndexMetaTable` storage classes back to SDK metadata objects, so storage-backed DataNodes can fail after attach/import even though registration appears successful.
2. New storage initialization helpers call a non-existent `initialize_source_table` method on SDK `TimeIndexMetaTable`, which is not part of the latest SDK machinery.
3. `external_registered` registration treats time-index DataNode storage classes as generic external SQLAlchemy meta tables, which bypasses SDK time-index registration semantics.

There are also packaging/version drift issues and two stale tests relative to SDK 4.1.5 parameter serialization.

## Validation Performed

Focused refactor tests:

```bash
.venv/bin/python -m pytest \
  tests/msm/data_nodes/test_contracts.py \
  tests/msm/data_nodes/test_asset_indexed_data_nodes.py \
  tests/msm/data_nodes/test_index_stamped_data_nodes.py \
  tests/msm/data_nodes/test_portfolio_contracts.py \
  tests/msm/assets/test_asset_snapshots.py \
  tests/msm_pricing/data_nodes/test_curves.py \
  tests/msm_pricing/data_nodes/test_index_fixings.py \
  tests/msm_pricing/test_meta_tables.py \
  tests/msm/models/test_metatable_models.py
```

Result: `111 passed, 4 skipped, 2 warnings`.

Full suite:

```bash
.venv/bin/python -m pytest
```

Result: `368 passed, 4 skipped, 2 failed, 2 warnings`.

The two failures are in repository tests that still expect Python `datetime` objects in compiled operation parameters. SDK 4.1.5 serializes typed temporal parameters for remote payloads, so the observed values are strings such as `2026-05-25T00:00:00Z`. This looks like stale test expectations rather than a refactor implementation failure, but it needs to be updated before the suite can be considered green against the current SDK.

## Findings

### P0: Storage catalog/platform paths bypass `PlatformTimeIndexMetaTable.register(...)`

Files:

- `src/msm/maintenance/catalog.py`
- `src/msm/models/registration.py`
- SDK reference: `mainsequence/meta_tables/data_nodes/data_nodes.py`
- SDK reference: `mainsequence/meta_tables/sqlalchemy_contracts.py`

The refactor correctly uses SDK `PlatformTimeIndexMetaTable.register(...)` in the fresh platform-registration path. That is the important SDK path because it builds the storage registration request from the SQLAlchemy class contract, sends it through the time-index registration endpoint, receives the canonical `TimeIndexMetaTable`, and binds that returned object to the local class.

The problem is that catalog/import/existing-resource paths can bypass that single lifecycle by reconstructing generic `MetaTable` objects or resolving generic metadata instead of going back through the storage class registration path.

For SDK DataNodes, the local class state after registration matters. The SDK checks that the `PlatformTimeIndexMetaTable` subclass has been registered/bound before DataNode construction. That state should be produced by `register`, not by a downstream manual attach path.

Impact:

- Bootstrap can appear successful while later DataNode construction fails because the SDK registration lifecycle was skipped.
- Catalog-driven attach/import does not necessarily reproduce the state created by SDK storage registration.
- The downstream library starts owning lifecycle behavior that should remain in the SDK registration path.

Recommended fix:

- Treat `PlatformTimeIndexMetaTable.register(...)` as the only idempotent get-or-create path for time-index storage classes.
- In catalog/import/existing-platform paths, if `is_time_index_meta_table_model(model)` is true, call `model.register(...)` with the same registration kwargs used in fresh registration.
- Treat catalog rows as validation/cache information for storage classes, not as a replacement for the SDK storage registration path.
- If `register` is not idempotent when the storage already exists, fix that in the SDK/backend registration behavior rather than adding a second bind/attach path in `ms-markets`.
- Add regression tests proving that storage classes are usable after catalog/import flows because those flows route through `register`.

### P0: New code calls non-SDK `initialize_source_table`

Files:

- `src/msm/services/holdings.py`
- `src/msm/portfolios/data_nodes/storage_initialization.py`
- SDK reference: `tests/test_data_node_storage_dimension_queries.py`
- SDK reference: `mainsequence/meta_tables/sqlalchemy_contracts.py`

The refactor introduces storage readiness helpers that call `storage.initialize_source_table(...)` on the DataNode storage metadata object.

That method is not part of SDK 4.1.5. The SDK test suite explicitly includes coverage that DataNode storage does not expose `initialize_source_table`. The latest SDK path for time-index storage registration is `PlatformTimeIndexMetaTable.build_registration_request(...)` and `TimeIndexMetaTable.register(...)`, with `time_index_name`, `index_names`, `table_contract`, and target foreign keys carried through the registration request/profile.

Impact:

- `AccountHoldings.ensure_storage_ready()` and `PortfolioCanonicalDataNode.ensure_storage_ready()` can raise `AttributeError` in real usage.
- This creates a hidden one-case extension point that is not an SDK API.
- It risks duplicating or bypassing backend initialization behavior that belongs to SDK/platform registration.

Recommended fix:

- Remove reliance on `initialize_source_table`.
- Ensure source-table initialization is expressed through the SDK registration metadata and platform registration path.
- If the platform truly needs an explicit initialization API, it should be added to the SDK first and used through that documented API, not assumed in this library.

### P1: `external_registered` mode bypasses time-index storage registration semantics

File:

- `src/msm/models/registration.py`

The model registry now contains both normal domain meta tables and time-index DataNode storage classes. The helper `is_time_index_meta_table_model(...)` detects SDK `PlatformTimeIndexMetaTable` models, and the platform registration path uses that distinction.

The `external_registered` path does not. It sends every model through generic external SQLAlchemy registration helpers:

- `external_registered_registration_request_from_sqlalchemy_model(...)`
- `register_external_sqlalchemy_model(...)`

That is valid for ordinary ORM meta tables, but not for `PlatformTimeIndexMetaTable` storage classes. Time-index storage classes need SDK time-index metadata, time-index profile, index names, and DataNode storage binding semantics.

Impact:

- In external mode, DataNode storage classes can become generic registered meta tables rather than SDK time-index metadata.
- DataNode construction/query functionality can fail or silently lose time-index semantics.
- Tests currently cover external domain requests, but they do not adequately prove external registration of storage classes works.

Recommended fix:

- Either reject `external_registered` for DataNode storage classes with a clear error, or implement a separate SDK-aligned external time-index registration path.
- Add tests specifically for `AssetSnapshotsStorage`, holdings storage, portfolio storage, and pricing storage under external mode.

### P1: Package metadata is not aligned with the SDK version used by the refactor

Files:

- `pyproject.toml`
- `uv.lock`
- `requirements.txt`

The current environment imports `mainsequence==4.1.5` from the local SDK checkout, but the project metadata does not consistently require that version:

- `pyproject.toml` has an unpinned `mainsequence` dependency.
- `uv.lock` locks `mainsequence==4.1.2`.
- `requirements.txt` pins `mainsequence==4.0.14`.

Impact:

- A clean install can use an SDK version older than the refactor expects.
- The refactor uses APIs and import paths that are current SDK concepts, such as `PlatformTimeIndexMetaTable` and `mainsequence.meta_tables.compiled_sql.v1`.
- CI and developer environments can disagree depending on whether they use the local checkout, lockfile, or requirements file.

Recommended fix:

- Set the minimum SDK version explicitly, likely `mainsequence>=4.1.5`, or use a workspace/path dependency for local development.
- Regenerate `uv.lock` and `requirements.txt` from the same source of truth.
- Add a simple import/version assertion in CI if this project is expected to track SDK development closely.

### P2: Repository tests are stale relative to SDK 4.1.5 compiled-SQL payloads

Files:

- `tests/msm/repositories/test_repositories.py`
- `src/msm/repositories/base.py`
- SDK reference: `mainsequence/meta_tables/compiled_sql/v1.py`
- SDK reference: `mainsequence/client/models_metatables.py`

The full suite failures are:

1. `test_generic_upsert_operation_populates_python_defaults_for_backend_sql`
2. `test_account_target_position_assignment_operation_requires_utc_timestamp`

Both failures are caused by test assertions expecting Python `datetime` values in compiled operation parameters. SDK 4.1.5 builds operations with parameter types, and `MetaTableStatementPayload` serializes typed temporal parameters for remote transport.

Impact:

- The suite is not green even though the implementation appears to be following the SDK compiled-SQL API.
- Future refactor validation will remain noisy until these assertions are updated.

Recommended fix:

- Update tests to expect serialized remote parameter values and parameter type metadata.
- Alternatively parse the serialized value back to `datetime` in the assertion if the intent is to prove UTC normalization.

### P2: DataNode configuration duplicates storage schema

Files:

- `src/msm/data_nodes/accounts.py`
- `src/msm/data_nodes/execution.py`
- `src/msm/portfolios/data_nodes/base.py`

Several new `DataNodeConfiguration` classes repeat values that are already owned by the storage class, such as `time_index_name` and `index_names`. The classes then validate the configuration against storage-derived constants.

This is safer than silently diverging, but it still leaves two sources of schema truth. The refactor's strongest direction is storage-first declaration. Configuration should ideally describe DataNode behavior/update scope/hash behavior, while storage schema should come from the `PlatformTimeIndexMetaTable` class.

Impact:

- More boilerplate in each DataNode type.
- Extra opportunity for mismatched config values.
- New storage-backed nodes will likely copy this pattern and increase maintenance cost.

Recommended fix:

- Derive time-index and index-name config directly from `storage_table` where possible.
- Keep only true DataNode behavior fields in the `DataNodeConfiguration` subclasses.

### P2: Similar frame validation logic is repeated across node families

Files:

- `src/msm/data_nodes/accounts.py`
- `src/msm/data_nodes/execution.py`
- `src/msm/portfolios/data_nodes/base.py`
- `src/msm/data_nodes/utils/storage_schema.py`

The refactor adds strong validation, which is good, but holdings, execution, and portfolio canonical nodes all repeat the same shape:

- Reset index if needed.
- Check required columns.
- Normalize timestamps.
- Coerce identifier columns.
- Sort by storage index columns.
- Reject duplicates.

`storage_schema.py` already centralizes some metadata extraction from SQLAlchemy storage classes, but the DataFrame validation layer still repeats a lot of storage-driven mechanics.

Impact:

- Validation rules can drift between storage-backed DataNode families.
- Adding another storage-backed node requires copying a fairly large pattern.

Recommended fix:

- Add a small shared helper that normalizes a frame against a `PlatformTimeIndexMetaTable` storage class.
- Keep domain-specific semantic checks in each DataNode class.
- Avoid a large generic framework; a narrow helper for required columns, timestamp coercion, sort keys, and duplicate-key validation is enough.

## What Is Well Aligned

The refactor has several strong design choices:

- Storage declarations are moving to SDK-native `PlatformTimeIndexMetaTable` classes.
- Storage schema is derived from SQLAlchemy columns through SDK type/token helpers instead of hand-maintained contract dictionaries.
- DataNode classes still call SDK superclass constructors with `config` and `storage_table`; they are not replacing the SDK `DataNode` lifecycle.
- The migration away from old `mainsequence.tdag` imports is consistent with the current SDK package layout.
- Compiled SQL usage is pointed at `mainsequence.meta_tables.compiled_sql.v1`, which matches the current SDK.
- Focused tests for storage contracts, asset-indexed nodes, portfolio contracts, pricing curves, fixings, and meta table models pass against the local 4.1.5 SDK checkout.

## Acceptance Checklist

Before accepting the refactor, I would require:

1. Existing-platform/catalog attach paths bind time-index storage classes to SDK `TimeIndexMetaTable` objects.
2. All `initialize_source_table` calls are removed or replaced with a real SDK API.
3. `external_registered` mode is made explicit for storage models: supported with SDK time-index semantics or rejected clearly.
4. SDK dependency metadata is made consistent across `pyproject.toml`, `uv.lock`, and `requirements.txt`.
5. The full test suite passes against `mainsequence==4.1.5`.
6. At least one integration-style test constructs a DataNode after catalog attach/import, not only after fresh registration.
7. Storage-backed frame validation is either centralized in a small helper or deliberately documented where domain-specific behavior requires separate implementations.

## Bottom Line

This is a substantial and mostly correct architectural move toward SDK-native storage-backed DataNodes. The main problem is not the intent of the refactor; it is that a few paths still treat SDK time-index storage as generic meta tables or assume backend methods that the SDK does not expose.

Fixing the attach/bind paths and removing `initialize_source_table` are the critical changes needed to make this a proper extension of `mainsequence-sdk` rather than a local compatibility layer that happens to pass the happy-path tests.

## Implementation Tasks To Align With SDK 4.1.5

The tasks below are intentionally ordered. The first three remove SDK contract violations; the later tasks clean up versioning, tests, and maintainability.

### Task 1: Route time-index storage reuse through `register`

Priority: P0

Goal: every supported bootstrap path should use `PlatformTimeIndexMetaTable.register(...)` as the single idempotent lifecycle for time-index DataNode storage.

Files to change:

- `src/msm/maintenance/catalog.py`
- `src/msm/models/registration.py`
- Tests under `tests/msm/maintenance/` or `tests/msm/models/`.

Implementation steps:

1. Find every branch that handles an existing catalog row or existing platform resource for a model.

2. If `is_time_index_meta_table_model(model)` is true, do not reconstruct a generic `MetaTable` from the catalog row and do not manually bind by UID. Instead call:

   ```python
   meta_table = model.register(
       **_platform_registration_kwargs(...),
   )
   ```

   The registration request should be built from the storage class contract and existing target FK mapping, exactly as in the fresh registration path.

3. Keep catalog row validation as an integrity check. It can compare expected contract fingerprints, but it should not replace the SDK time-index registration lifecycle.

4. For ordinary non-time-index meta tables, keep the existing catalog/import logic unless it also bypasses an SDK-required registration invariant.

5. Add regression coverage parameterized across representative `PlatformTimeIndexMetaTable` subclasses. The test should prove that after the catalog/import path runs, a DataNode can be constructed using that storage class.

Acceptance criteria:

- Time-index storage classes always become usable through `PlatformTimeIndexMetaTable.register(...)`.
- No alternate downstream lifecycle is introduced for DataNode storage.
- Generic `MetaTable` placeholders are not used as the lifecycle object for `PlatformTimeIndexMetaTable` subclasses.
- If the backend returns an already-existing storage resource, `register` still returns the canonical `TimeIndexMetaTable` and the SDK class is ready for DataNode construction.

### Task 2: Remove `initialize_source_table` usage

Priority: P0

Goal: do not call non-SDK methods on SDK metadata objects. Storage/source-table readiness must flow through SDK registration metadata or a real SDK API.

Files to change:

- `src/msm/services/holdings.py`
- `src/msm/portfolios/data_nodes/storage_initialization.py`
- Any tests currently expecting explicit source-table initialization through these helpers.

Implementation steps:

1. Remove helper logic that calls `storage.initialize_source_table(...)`.

2. Trace why `ensure_storage_ready()` exists for each DataNode family:

   - If it only ensures storage registration, replace it with checks that the storage class is registered/bound through SDK metadata.
   - If it tries to create backend/source tables, move that responsibility to the SDK/platform registration path.
   - If a backend operation is still genuinely needed, add or request a proper SDK API first, then call that documented API.

3. Keep public methods such as `ensure_storage_ready()` only if they still express a valid library-level concept. They should validate readiness, not synthesize backend state through undeclared platform methods.

4. Add tests that prove the readiness path works with actual SDK metadata objects that do not define `initialize_source_table`.

Acceptance criteria:

- `rg "initialize_source_table" src tests` returns no application usage unless the SDK has introduced this as a documented method.
- `AccountHoldings.ensure_storage_ready()` and portfolio canonical readiness do not raise `AttributeError` under SDK 4.1.5.
- Storage initialization is not duplicated outside SDK registration machinery.

### Task 3: Make `external_registered` explicit for time-index storage

Priority: P1

Goal: prevent storage classes from being registered as generic external SQLAlchemy meta tables.

Files to change:

- `src/msm/models/registration.py`
- Registration tests for external mode.

Implementation options:

Option A: reject storage classes in `external_registered` mode.

- This is the safer first implementation if the SDK does not currently support externally registered time-index storage.
- Detect `is_time_index_meta_table_model(model)` and raise a clear error explaining that storage-backed DataNodes must use platform time-index registration.

Option B: implement SDK-aligned external time-index registration.

- Use SDK APIs that produce or register `TimeIndexMetaTable` with the same profile fields as platform registration.
- Bind the returned `TimeIndexMetaTable` back to the storage class.
- Do not use `external_registered_registration_request_from_sqlalchemy_model(...)` for storage classes.

Recommended path:

- Start with Option A unless there is a confirmed SDK-supported external time-index registration API.
- Add a TODO only if tied to a real SDK issue/task; do not leave silent fallback behavior.

Acceptance criteria:

- External registration tests cover both ordinary domain meta tables and time-index storage classes.
- Storage models are either rejected clearly or registered as real time-index metadata.
- No `PlatformTimeIndexMetaTable` subclass goes through generic external SQLAlchemy registration.

### Task 4: Normalize SDK dependency declarations

Priority: P1

Goal: clean installs and CI must use the SDK version this refactor targets.

Files to change:

- `pyproject.toml`
- `uv.lock`
- `requirements.txt`
- CI/developer setup docs if present.

Implementation steps:

1. Decide the intended dependency strategy:

   - Published SDK dependency: set `mainsequence>=4.1.5`.
   - Monorepo/local development: use a path/workspace override to the local SDK checkout.

2. Update `pyproject.toml` first, then regenerate lockfiles from it.

3. Do not manually edit only `requirements.txt`; make it an exported artifact from the same dependency source.

4. Add a small CI check or import-time diagnostic if this package is expected to track SDK development very closely.

Acceptance criteria:

- `pyproject.toml`, `uv.lock`, and `requirements.txt` agree on the SDK version strategy.
- A clean environment imports an SDK version with `PlatformTimeIndexMetaTable` and `mainsequence.meta_tables.compiled_sql.v1`.
- The refactor no longer depends on an implicit local editable SDK checkout.

### Task 5: Update stale compiled-SQL temporal parameter tests

Priority: P2

Goal: make tests match SDK 4.1.5 remote payload behavior.

Files to change:

- `tests/msm/repositories/test_repositories.py`

Implementation steps:

1. Update assertions that inspect compiled operation parameters for temporal fields.

2. Expect serialized remote values when parameter type metadata is present, for example `2026-05-25T00:00:00Z`, or parse the serialized value back to a UTC `datetime` before comparing.

3. Also assert that parameter type metadata is present. That proves the SDK had enough information to serialize correctly.

Acceptance criteria:

- Full test suite passes against SDK 4.1.5.
- Tests still prove UTC normalization and backend payload correctness.
- Tests do not require internal SDK behavior that changed intentionally in 4.1.5.

### Task 6: Centralize storage-backed DataFrame normalization carefully

Priority: P2

Goal: reduce repeated validation code without hiding domain-specific semantics.

Files to change:

- `src/msm/data_nodes/utils/storage_schema.py` or a neighboring helper module.
- `src/msm/data_nodes/accounts.py`
- `src/msm/data_nodes/execution.py`
- `src/msm/portfolios/data_nodes/base.py`

Implementation steps:

1. Extract only the mechanical storage-driven operations:

   - Reset index when index columns are present in the frame index.
   - Check required storage columns.
   - Normalize the time-index column.
   - Coerce identifier/index columns using storage schema hints.
   - Sort by declared storage index columns.
   - Detect duplicate storage keys.

2. Keep domain logic local:

   - Holdings-specific value semantics.
   - Execution-specific optional columns or order behavior.
   - Portfolio canonical constraints.

3. Prefer one small helper over a broad validation framework. The helper should take a storage model and a DataFrame, then return a normalized DataFrame plus clear validation errors.

Acceptance criteria:

- Holdings, execution, and portfolio canonical validators are shorter but still readable.
- Tests still cover domain-specific validation failures.
- A new storage-backed DataNode can reuse the helper without copy-pasting a full validator.

### Task 7: Reduce schema duplication in DataNode configuration

Priority: P2

Goal: keep `PlatformTimeIndexMetaTable` classes as the single source of truth for storage schema.

Files to change:

- `src/msm/data_nodes/accounts.py`
- `src/msm/data_nodes/execution.py`
- `src/msm/portfolios/data_nodes/base.py`

Implementation steps:

1. Remove `time_index_name` and `index_names` from DataNode configuration when they can be derived from `storage_table`.

2. Keep configuration fields that affect DataNode behavior, update policy, hash identity, or user-visible node semantics.

3. If any external API currently exposes these config fields, deprecate them gradually rather than breaking callers abruptly.

Acceptance criteria:

- Storage schema exists in one place: the storage SQLAlchemy class.
- DataNode config no longer needs defensive checks against identical storage constants.
- Serialized DataNode config remains stable for fields that actually affect node identity/behavior.

### Task 8: Add end-to-end registration mode coverage

Priority: P2

Goal: prove the refactor works beyond the fresh-registration happy path.

Tests to add or extend:

- Fresh platform registration for at least one storage-backed DataNode.
- Existing-platform attach for the same DataNode.
- Catalog import/attach for the same DataNode.
- External mode behavior for ordinary meta tables and storage classes.

Minimum recommended cases:

- `AssetSnapshotsStorage`
- `AccountHoldingsStorage`
- one portfolio canonical storage class
- one pricing storage class, such as fixings or curves

Acceptance criteria:

- Every supported registration mode either works and binds SDK state correctly, or fails with an intentional clear error.
- Tests assert DataNode construction, not just registration request shape.
- Tests check the class-level SDK binding state after attach.

### Task 9: Mark ADR 0017 completed after alignment is finished

Priority: P2

Goal: keep the architecture record accurate once the implementation actually follows the SDK storage lifecycle.

Implementation task:

- [ ] Mark ADR 0017 as completed only after the P0/P1 alignment tasks are implemented and the full test suite passes against the intended SDK version.

Acceptance criteria:

- ADR 0017 is not marked complete while storage registration, `initialize_source_table`, external mode, or SDK dependency drift remains unresolved.
- The ADR status change references the verification evidence: SDK version, test command, and pass/fail result.

## Suggested Implementation Order

1. Route time-index storage reuse through `PlatformTimeIndexMetaTable.register(...)`.
2. Remove `initialize_source_table` and route readiness through SDK registration metadata.
3. Decide and enforce `external_registered` behavior for storage classes.
4. Align dependency metadata and lockfiles to SDK 4.1.5.
5. Update stale compiled-SQL temporal tests.
6. Add end-to-end registration mode tests.
7. Mark ADR 0017 completed after the P0/P1 alignment work and verification are done.
8. Refactor repeated frame normalization and config duplication only after the SDK contract fixes are stable.

This order keeps behavioral correctness ahead of cleanup. The DRY improvements are useful, but they should not be done before the storage registration lifecycle is correct.

## Storage Registration Path

The correct alignment path is to keep `PlatformTimeIndexMetaTable.register(...)` as the single storage lifecycle operation.

For storage-backed DataNodes, the downstream library should not introduce a second public lifecycle. The UID of a `TimeIndexMetaTable` is an output of registration/resolution. It should not be required as an input before the storage class can become usable.

The expected SDK invariant is:

```python
registered = SomePlatformTimeIndexStorage.register(...)

assert SomePlatformTimeIndexStorage.get_time_index_metadata() is registered
assert SomePlatformTimeIndexStorage.get_meta_table_uid() == registered.uid
```

Those assertions are useful only as verification that `register` performed the canonical SDK lifecycle: build request, register-or-resolve on the backend, return the canonical `TimeIndexMetaTable`, and make the class ready for DataNode construction.

The refactor should therefore remove catalog/import behavior that replaces this lifecycle with generic `MetaTable` reconstruction for `PlatformTimeIndexMetaTable` subclasses. Catalog rows can still be used to validate expected contract information, but storage classes should be made usable by calling `register`.

If `register` is not idempotent when a storage resource already exists, the SDK/backend registration behavior should be fixed. `ms-markets` should not compensate by implementing a second storage-binding mechanism.
