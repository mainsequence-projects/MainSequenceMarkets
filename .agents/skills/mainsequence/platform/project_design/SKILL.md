---
name: project-design
description: Design, explain, review, and maintain a Main Sequence project architecture and its connected Project Blueprint. Use for initial project design, architectural changes, ontology maintenance, Blueprint review or reconciliation, and implementation handoff across MetaTables, TimeIndexMetaTables, DataNodes, jobs, APIs, CLI commands, project-to-agent skills, and static sites.
---

# Main Sequence Project Design

Act as the project architect. Translate user intent into a connected,
project-owned Blueprint that another agent can implement without reconstructing
the architecture from unrelated lists.

The MCP server delivers this skill, the platform ontology, and approved
operations. It does not contain an LLM, plan the project, or write the
Blueprint. Perform the reasoning in the calling agent.

## Preserve The Ownership Boundary

Own:

- project intent and success criteria;
- project-domain concepts, relationships, and invariants;
- architectural selection and rationale;
- cross-component dependencies;
- Blueprint creation, review, change, reconciliation, and handoff.

Do not own:

- Python, SDK, package, migration, or virtual-environment mechanics;
- local Git and filesystem operations;
- concrete implementation code;
- DRF persistence or platform runtime state;
- deployment execution;
- secret values or runtime credentials.

Use the SDK and domain execution skills after the design is accepted. For a
static-site frontend, the complete version-matched skill bundle shipped by the
project's installed `@dev-mainsequence/command-center-sdk` package owns the
frontend implementation; the MCP `static-site` skill owns only the platform
release workflow.

When accepted project intent requires financial-markets functionality, select
`ms-markets`, record the selection and rationale in `decisions` and the
affected components' `depends_on` entries, and defer all financial-market
domain and implementation guidance to the skills shipped by `ms-markets`.

## Load Platform Meaning

Read `mainsequence://platform/ontology` before selecting platform concepts.
Keep these distinctions:

- `Project` is the logical platform aggregate. It owns the canonical
  user-facing name, lifecycle, labels, sharing, and its complete collection of
  ProjectBranches.
- `GitRepository` is the provider/source-control record. Repository detail
  exposes its owning logical Project UID and never selects an entry, main,
  oldest, or current ProjectBranch.
- `ProjectBranch` is one durable branch-specific configuration and execution
  context under a Project. Another provider branch gets a different
  ProjectBranch UID while retaining the same logical Project UID.
- `project.create` establishes the logical Project and its initial `main`
  ProjectBranch and never accepts a branch name. An existing provider branch is
  linked later through the canonical GitRepository branch-import operation;
  do not create a second logical Project for it. The import inherits the main
  ProjectBranch `metatables_data_source` when omitted or may use another
  caller-accessible DataSource as that branch context's MetaTable-oriented
  default.
- `DataSource` is the sole canonical database identity. There is no project
  data-source wrapper or generic Project-to-DataSource membership.
- `MetaTable` is the platform catalog boundary for a physical relational
  table and points directly to its canonical DataSource. Project-owned table
  shapes are authored in SQLAlchemy metadata and bound to
  PostgreSQL/TimescaleDB, MySQL, or SQL Server data sources.
- `TimeIndexMetaTable` is the `MetaTable` specialization for time-indexed
  storage. It owns the time index, cadence, ordered identity dimensions,
  partition strategy, and time-series progress behavior.
- `DataNode` is deterministic update logic that produces or maintains
  `TimeIndexMetaTable` data; its database identities are derived from its
  input and output MetaTables.
- `Job` is a project-bound execution definition with a repository execution
  path or app target, runtime resources, optional image/commit pinning, and an
  optional schedule. `JobRun` is one execution.
- An API is a consumer and composition surface, not hidden producer logic.
- A project CLI command is an executable project interface, not the platform
  permission authority.
- `project_to_agent` exposes verified project CLI workflows as truthful
  project-agent skills; it is not generic Agent administration.

Use the platform ontology for global platform nouns. Define the project's own
business concepts inside the Blueprint.

## Choose The Interaction Mode

Use one Blueprint contract in both modes.

### Guided Mode

Default to guided mode when the user's experience is unknown.

- Ask one material architecture question at a time.
- Define each platform term before relying on it.
- Explain why each component is needed.
- Explain alternatives and why they were rejected.
- Explain grain, keys, relationships, constraints, dependencies, lifecycle,
  and failure consequences.
- Write detailed rationale and acceptance criteria into the Blueprint.

For a MetaTable, explain what one row means, why its keys express that grain,
why each relationship needs a foreign key or constraint, and which access
pattern justifies an index. State the physical database dialect because it
affects the SQLAlchemy types, defaults, and constraint behavior.

For a DataNode, explain the produced dataset, complete output grain, cadence,
dependencies, incremental boundary, determinism, and consumers.

### Advanced Mode

Use advanced mode when the user requests it or demonstrates the relevant
platform knowledge.

- Accept compact technical intent.
- State assumptions in batches.
- Focus on invariants, tradeoffs, risks, and architecture changes.
- Keep rationale concise but complete.
- Prefer a Blueprint diff when maintaining an existing design.

Never reduce architectural rigor in advanced mode.

## Start From Intent

Establish:

- the problem and project boundary;
- users and consuming systems;
- outcomes and observable success criteria;
- business concepts and relationships;
- required data, computation, interfaces, and schedules;
- security, ownership, latency, and operating constraints.

Separate verified facts, assumptions, decisions, and open questions. Ask only
for information that materially changes the architecture or authorization
boundary.

Do not start from a list of platform records.

## Maintain The Project Ontology

Define project concepts before mapping them to implementation components.

For each concept, record:

- a stable project-local key;
- human-facing name;
- precise definition;
- business identity;
- source of truth;
- important attributes;
- lifecycle when the concept changes state.

For each relationship, record:

- subject, predicate, and object concept references;
- cardinality;
- required or optional participation;
- governing invariant;
- the components that materialize or enforce it.

Record invariants as testable statements. Do not use a database table name as
the definition of a business concept.

## Produce One Connected Blueprint

Produce or update one project-owned, version-controlled YAML document with this
top-level structure:

```yaml
blueprint_version: "1"

project:
  purpose: ...
  users: ...
  outcomes: ...
  success_criteria: ...

ontology:
  concepts: ...
  relationships: ...
  invariants: ...

decisions: ...
open_questions: ...

metatables: ...
data_nodes: ...
jobs: ...
apis: ...
cli: ...
project_to_agent: ...
static_sites: ...
```

The exact repository path is project policy until the platform approves one.
When no path is established, return the complete YAML for review instead of
inventing a location.

## Use Local References

Give every reusable Blueprint item a stable key. Reference it with its section:

```text
project.outcomes.daily_portfolio_risk
ontology.concepts.portfolio
metatables.portfolios
data_nodes.calculate_daily_portfolio_risk
jobs.nightly_reconciliation
apis.portfolio_risk_api
cli.calculate_portfolio_risk
project_to_agent.skills.portfolio_risk_analysis
```

These references exist only inside the Blueprint. They do not allocate a
backend record, replace a public UID, or create a platform registry.

Do not require platform UIDs for planned components. Never use numeric database
identifiers. Use a public UID only in a platform operation after verifying an
existing object through the canonical operation.

## Connect Every Component

For every MetaTable, DataNode, Job, API, CLI command, and static site, record:

- `key` and human-facing `name`;
- `purpose`;
- `rationale`;
- `fulfills` outcome references;
- `domain_concepts` references;
- typed dependencies;
- consumers;
- constraints;
- acceptance criteria;
- relevant decision references.

Reject orphan components that support no outcome or have no meaningful
consumer.

`depends_on`, `consumers`, and acceptance criteria are Blueprint architecture
links. Do not misrepresent them as persisted fields on a MetaTable, DataNode,
Job, API, or CLI record.

## Design MetaTables

Use a MetaTable for a project table whose shape is authored in SQLAlchemy or
for an existing physical relational table registered into the platform.

For a project-owned table, SQLAlchemy metadata is the authored table shape.
The physical backend is one of PostgreSQL/TimescaleDB, MySQL, or SQL Server.
Record the dialect explicitly and keep the shape compatible with it. Do not
turn the Blueprint into Python code.

Record:

- relational or time-indexed table kind;
- physical database dialect: `postgresql`, `timescaledb`, `mysql`, or `mssql`;
- management mode: `platform_managed` or `external_registered`;
- schema-management mode: `backend_managed`, `alembic_managed`, or
  `external_registered`;
- SQLAlchemy table name;
- row grain in one precise sentence;
- business key;
- columns with SQLAlchemy/logical type, optional dialect-specific backend type,
  meaning, nullability, default behavior, and concept;
- primary and unique constraints;
- foreign keys with their ontology relationship and rationale;
- indexes with the lookup, join, ordering, or uniqueness need that justifies
  them;
- producers and consumers.

Do not add a foreign key, index, or constraint without explaining its semantic
or access-pattern purpose. Do not confuse an index with a business invariant.
For application-owned schema evolution, SQLAlchemy/Alembic owns physical DDL;
MetaTable owns catalog identity, permissions, physical-table binding, and
introspected metadata.

## Design DataNodes

Use a DataNode for deterministic computation that incrementally produces or
maintains `TimeIndexMetaTable` data.

Record:

- the output `TimeIndexMetaTable` reference (stored in the Blueprint's existing
  `output_metatable` field);
- complete output grain: time index plus all identity dimensions;
- cadence and freshness expectation;
- DataNode, MetaTable, and external-data dependencies;
- update boundary and partitioning;
- determinism and idempotency expectations;
- backfill and replay behavior;
- lineage and downstream consumers.

Require the DataNode output grain to agree with its output
`TimeIndexMetaTable`. Keep storage shape in the table resource and update
behavior in the DataNode.

## Design Jobs

Use a Job for project code that should execute manually or on an optional
interval/crontab schedule and does not belong in deterministic DataNode
production or a request-time API.

Record:

- `name`;
- exactly one execution target:
  - repository-relative `execution_path` for a `.py`, `.ipynb`, or `.yaml`
    project file; or
  - `app_name` for the existing app target;
- optional project commit and project-image pinning intent;
- `cpu_request` and `memory_request`;
- optional `gpu_request` and `gpu_type`;
- `spot`;
- positive `max_runtime_seconds`;
- optional `task_schedule` using the existing interval or crontab schedule
  shape, including start-time or one-off intent when needed.

The canonical creation flow infers the Job type from `execution_path` or
`app_name`. Do not declare an independent type or command contract in the
Blueprint.

Explain why the workload is a Job rather than a DataNode, API request, or local
developer command.

Do not invent Job fields for retry policy, failure policy, queues, dependency
graphs, output schemas, or completion callbacks. A Job invocation creates a
JobRun whose existing runtime status is observed separately. The Blueprint's
cross-component references and acceptance criteria do not become Job model
fields.

## Design APIs

Use an API as a typed project interface over accepted business behavior and
data.

Record:

- intended consumers;
- reads-from and writes-to references;
- operations with purpose, method/path intent, request contract, response
  contract, and read/mutation classification;
- authentication and authorization expectations;
- latency and availability expectations;
- error behavior;
- deployment/release expectation;
- acceptance criteria.

Do not rebuild producer logic in an API. Reference the DataNode or MetaTable
that owns the data.

## Design The Project CLI

Use `cli` to define the project's executable human-, automation-, and
agent-facing command surface.

For each command, record:

- an exact command path;
- purpose and rationale;
- the components it reads, writes, invokes, or inspects;
- typed inputs with meaning, requiredness, and validation;
- machine-readable output contract;
- `read` or `mutation` side effects;
- authorization and preconditions;
- failure and retry behavior;
- examples and acceptance criteria.

The command must map to real project behavior. Do not place platform permission
policy only in the CLI.

## Design Project To Agent

Use `project_to_agent` only when the project itself should become a
project-backed agent.

Record:

- whether it is enabled;
- a human-facing role name, purpose, and rationale;
- explicit boundaries;
- project-agent skills.

For every project-agent skill, record:

- key, name, factual description, and rationale;
- one or more exact `cli` command references;
- when-to-use guidance and workflow;
- inputs, outputs, constraints, examples, and acceptance criteria.

Require every skill to reference at least one declared CLI command. A skill may
compose several commands into a user workflow, but it must not duplicate the
command contract, hide a mutation, or invent project behavior.

Use the separate `project-to-agent` platform skill to prepare repository
instructions, project-owned skill files, and the source card after the
Blueprint is accepted and the referenced CLI behavior exists.

## Design Static Sites

Use `static_sites` when the project needs a browser frontend deployed through a
static ResourceRelease. Keep the item connected to project outcomes, domain
concepts, consumers, and accepted APIs. Do not turn the Blueprint into a
route-by-route UI specification, a frontend scaffold, a Command Center SDK
contract, or a duplicate ResourceRelease request.

Record:

- a stable key, human-facing name, purpose, and rationale;
- `fulfills` project-outcome references;
- `domain_concepts`, `depends_on`, `consumers`, `constraints`, and
  `decision_refs` from the common component contract;
- `deployment.root_directory`, `deployment.routing_mode`, and
  `deployment.automatic_deployment` only when those deployment choices are
  already accepted; and
- observable acceptance criteria.

Represent an API dependency through `depends_on`, using its `apis.<key>`
reference. Do not invent a build-environment variable name in project design;
transport configuration belongs to the frontend implementation selected
through the installed Command Center SDK skills.

Do not put API URLs, environment values, tokens, credentials, provider state,
framework versions, Node versions, output defaults, or a copy of the
ResourceRelease serializer in the Blueprint. The complete installed Command
Center SDK skill bundle owns frontend implementation. The separate MCP
`static-site` skill reads the canonical live capabilities and owns release
creation, deployment, and deployment-state observation only.

Use this compact shape:

```yaml
static_sites:
  portfolio_console:
    name: Portfolio Console
    purpose: Provide the browser interface for portfolio analysis.
    rationale: Users need an interactive presentation over the accepted API.
    fulfills:
      - project.outcomes.interactive_portfolio_analysis
    domain_concepts:
      - ontology.concepts.portfolio
    depends_on:
      - apis.portfolio_analysis
    consumers:
      - project.users.portfolio_manager
    constraints:
      - Must be usable from the supported Command Center application surface.
    decision_refs:
      - decisions.browser_frontend
    deployment:
      root_directory: frontend
      routing_mode: spa
      automatic_deployment: true
    acceptance_criteria:
      - The supported production build succeeds.
      - Portfolio analysis is usable by the intended browser consumers.
```

## Validate The Blueprint

Before handoff, verify:

- all keys are unique within their scopes;
- every local reference resolves;
- every component fulfills an outcome;
- every referenced ontology concept exists;
- every relationship names valid concepts;
- every MetaTable has explicit grain and keys;
- foreign keys cite compatible target keys and ontology relationships;
- indexes cite concrete access patterns;
- every DataNode output and grain agree with its MetaTable;
- API data dependencies resolve;
- every CLI command maps to real components and declares side effects;
- every project-agent skill references at least one compatible CLI command;
- every static-site dependency and consumer reference resolves;
- static-site deployment intent contains only currently approved canonical
  release fields;
- no static-site item duplicates frontend implementation or Command Center SDK
  contracts;
- no secret, credential, provider location, numeric database ID, or transient
  run state appears.

Report validation errors against exact Blueprint paths. Do not silently repair
an accepted architectural decision.

## Maintain Rather Than Rebuild

For an existing Blueprint:

1. Read the current Blueprint and relevant platform/repository evidence.
2. Identify drift between accepted intent and verified implementation.
3. Separate architecture drift from ordinary implementation defects.
4. Propose the smallest coherent Blueprint change.
5. Preserve stable keys unless the concept itself is replaced.
6. Update affected decisions, references, and acceptance criteria together.
7. Hand only accepted changes to execution skills.

Git owns document history. Do not embed a second change ledger in the
Blueprint.

## Verify Platform State

Use approved platform reads to verify existing objects, permissions, and state.
Treat not-found as non-disclosure when the canonical operation does so.

The concrete `project.create` tool accepts canonical DRF project-creation
fields. It does not accept natural-language intent or a Project Blueprint.
Resolve intent first, then call the typed operation only when action is
requested.

Do not send `repository_branch` to `project.create`; the server creates `main`.
GitRepository branch discovery and import are not MCP tools in the current
catalog, so do not claim that an MCP-only client can perform those workflows
until a separately approved tool exists. Canonical DRF repository detail
returns the owning logical Project UID; it never computes a branch UID. A
client invoking canonical DRF branch import may select its optional accessible
`metatables_data_source_uid`; if omitted, the server inherits the logical
Project `default_metatables_data_source`.

Choose the public `project_type` deliberately when the design establishes the
primary scaffold: `python` or `vite_react`. Omission means `python` for backward
compatibility. Do not invent separate language, framework, profile, or scaffold
version fields. The canonical response exposes the derived technology, the
mandatory pinned framework image, and repository/commit-scoped SDK
observations. A Vite ProjectBranch may omit `metatables_data_source_uid` and
must keep browser build variables on its StaticSiteRelease rather than
ProjectBranch `env_vars`. Project creation itself always requires
`default_metatables_data_source_uid`, exposes the safe Project default
projection, and assigns that DataSource to the initial main ProjectBranch.
Do not infer framework-image paths, tags, or runtime versions: the physical
infrastructure producer advertises those values, and Project creation resolves
its advertised default when no image UID is supplied.

Never claim that a mutation succeeded until the canonical response confirms
it. After an ambiguous result, retrieve or search before deciding whether to
retry.

When a newly created or existing Project must become a local checkout, hand
that separate lifecycle step to the `project-local-setup` platform skill. That
skill waits for repository initialization, registers only a caller-generated
public deploy key, and defines the host-managed clone and authentication
handoff. Project design never handles local paths, SSH private keys, or
credential values.

## Handoff

Return:

1. the complete or updated Blueprint;
2. the interaction mode used;
3. verified facts and evidence;
4. assumptions and open questions;
5. architectural decisions and consequences;
6. validation results;
7. the execution skill responsible for each accepted component.

Keep logical architecture separate from implementation. Do not include Python
imports, dependency pins, virtual-environment commands, local absolute paths,
or generated credentials.

## Stop Conditions

Stop and ask for direction when:

- two materially different architectures satisfy the intent;
- a required ownership or authorization decision is missing;
- platform evidence contradicts a user assumption;
- a required concept has no approved Blueprint contract;
- the requested operation is not exposed through an approved interface;
- implementation would start before the Blueprint decision is accepted.
