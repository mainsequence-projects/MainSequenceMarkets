---
name: project-design
description: Design, explain, review, and maintain a Main Sequence project architecture and its connected Project Blueprint. Use for initial project design, organization-environment architecture, architectural changes, ontology maintenance, Blueprint review or reconciliation, and implementation handoff across MetaTables, TimeIndexMetaTables, DataNodes, jobs, APIs, CLI commands, project-to-agent skills, and static sites.
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
frontend implementation. The MCP `resource-release` skill owns shared release
creation, configuration, deployment, and state observation; the `static-site`
skill owns only the static-specific capability and frontend handoff.

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
- `OrganizationProjectEnvironment` is the canonical operational partition of
  the platform. For Project-owned code and resources, the exact Git branch is
  the repository-side partition marker and `ProjectBranch` is the durable
  platform context that binds one logical Project to exactly one Environment.
  Another provider branch gets a different ProjectBranch UID while retaining
  the same logical Project UID, allowing one Project to participate in several
  Environment partitions without duplicating the Project.
- Never model a branch-owned object against `Project` alone and then infer an
  active, default, main, or current branch. Resolve the exact persisted
  `ProjectBranch`; all of its Jobs, images, releases, runtimes, Project Coding
  Agents, and repository-derived resources stay in that branch's Environment.
  A commit SHA shared by several branches does not merge their partitions.
- A Project Coding `Agent` derives its ProjectBranch and Organization
  Environment from the typed Project Executor policy. Agent list/search always
  selects one Organization Environment and returns only Project Coding Agents
  in that boundary. Human and local callers resolve the visible environments
  with `organization_environment.list` and ask the user to select one before
  discovery; deployed Project Executors use the backend-injected environment
  and never ask. Same-environment delegation additionally requires persisted
  parent-session provenance; environment membership is not blanket session or
  task authorization.
- `project.create` establishes the logical Project and its initial `main`
  ProjectBranch and never accepts a branch name. After bootstrap, a signed
  provider push links an existing branch automatically only when the
  Organization administrator has already created the exact matching
  environment; do not create a second logical Project for it. Git never creates
  the environment, and no manual branch-import workflow is accepted. The
  backend assigns each branch to the same-Organization environment whose
  immutable required branch exactly matches; the caller never supplies an
  environment UID.
- `OrganizationProjectEnvironment` is shared by exact compatible
  ProjectBranches from one or several Projects. Its DataSource is routing
  configuration, not environment identity.
- `DataSource` is the sole canonical physical database identity. New
  MetaTable work routes through the ProjectBranch's backend-derived
  Organization Environment; there is no generic Project-to-DataSource
  membership.
- `MetaTable` is the platform catalog boundary for a physical relational
  table. Platform-managed rows belong directly to one Organization Environment
  and use its canonical DataSource. External-registered rows, including
  Connection/DataSource imports, may remain Organization-scoped or be attached
  to an environment while retaining their selected DataSource. Project-owned
  table shapes are authored in SQLAlchemy metadata and bound to
  PostgreSQL/TimescaleDB, MySQL, or SQL Server data sources.
- `TimeIndexMetaTable` is the `MetaTable` specialization for time-indexed
  storage. It owns the time index, cadence, ordered identity dimensions,
  partition strategy, and time-series progress behavior.
- `DataNode` is deterministic update logic that produces or maintains
  `TimeIndexMetaTable` data; its database identities are derived from its
  input and output MetaTables.
- `Job` is a project-bound execution definition with a repository execution
  path or app target, runtime resources, exactly one ownership-typed image
  identity through the exclusive public/Organization relation pair, an exact
  full commit for project code, optional future exact-event image promotion,
  and an optional schedule. `JobRun` is one execution and freezes that image,
  digest, and commit before launch. A branch-owned Job,
  Project Executor, or runtime ResourceRelease may execute only a
  digest-pinned project image whose verified source provenance matches the
  exact ProjectBranch and commit. The backend admits source only after proving
  the full commit is reachable from that branch's exact remote ref and then
  stages one normalized checksummed compressed context in the output tenancy.
  Every image-build run protects that immutable relational artifact; GCP and
  Azure derive request locations from it, and retries never reclone Git,
  reinterpret provider strings, or choose branch state. Project authors and
  MCP callers never provide a bucket, object key, source URI, or signed token.
- Image ownership is explicit: public bases, tools, and bundles are
  `PublicCatalogImage`; Organization build outputs are
  `ProjectJobImage` descendants of `OrganizationImage`. There is no generic
  persisted `Image`, generic UID resolver, or cross-root discovery path.
- Every image-dependent `DeploymentRun` binds its exact image roles through
  typed `DeploymentRunImageDependency` rows. Active runs retain the live
  relation; terminal history may retain a typed tombstone after canonical
  image deletion. One complete
  `ProjectImageBuildRun` owns immutable build identity, provider request and
  operation state, a protected exact build-context artifact, reconciliation
  deadlines, and failure. Preparation commits before provider submission;
  database state is the durable queue and Celery is only a wake-up. Generic
  JSON never owns image UIDs, build-context artifact identities, source URIs,
  digests, provider handles, or readiness.
- Concurrent target services requesting the same exact image build converge on
  one canonical attempt and attach independent parent dependencies. Ambiguous
  submission remains on that attempt and is never blindly retried. Execution
  accepts only verified digest-pinned dependencies and never a `latest` tag.
- When a runtime ResourceRelease is declared in `.mainsequence/workflows` with
  automatic deployment enabled, project design does not select or require an
  image. The workflow ignores any image UID and validation accepts the
  declaration without one. On first application the backend resolves the exact
  repository-event image identity before materializing the backing Job; the
  target remains non-runnable until that image is verified and digest-pinned.
  Initial application owns one `source=create`, `operation=build_and_deploy`
  run and waits for that image when necessary. Later repository events own
  policy evaluation and use `source=repository_event` runs. Direct
  ResourceRelease creation remains a separate ready-image-backed
  `source=create`, `operation=deploy` contract.
- A widget extension is a `resource_release` deployment specialization, not a
  new Blueprint design domain. Handoff uses `release_kind: widget_extension`
  with only `name` and optional `root_directory`; automatic deployment and the
  fixed SDK workload build are backend-owned. Never design an `extension_id`,
  image selector, build command, environment, active deployment, or a second
  publication-attempt system.
- Workflow APIs `2.0.0` and `2.1.0` can carry non-secret target-owned `env_vars` for Jobs,
  runtime ResourceReleases, and Project Coding Agents. Static sites use
  `build_environment`; widget extensions accept neither. These literals configure only the declared target or
  its backing Job: they do not create or resolve platform Secrets/Constants,
  select an Organization Environment, write branch-wide configuration, or
  enter project-image builds.
- A deployed branch-owned runtime receives a backend-derived public context
  containing logical Project UID, exact ProjectBranch UID, descriptive branch
  name, and Organization Environment UID. That authenticated target chain is
  the resource-composition and routing authority, not the action principal.
  Every runtime credential authenticates one persisted responsible User, and
  normal DRF, role, service-identity, object, and operation authorization
  applies to that User without a token-scope action allowlist. Git is used only
  by a genuine local checkout to discover a persisted ProjectBranch; a
  deployed image never requires `.git` and cannot select another branch or
  environment.
- For Agent execution, distinguish the runtime responsible User from the
  AgentSession owner. The runtime responsible User authorizes and audits the
  service action; `AgentSession.created_by_user` owns the invocation and its
  model-provider credentials. An A2A child and handle inherit that User from
  the exact immediate parent session, whose Agent proves the calling service.
  Every target runtime hydrates independently after exact session
  authorization; credentials never travel in A2A content and service ownership
  is never a credential fallback.
- SDK application code never supplies deployed runtime mode, ProjectBranch,
  repository branch, or Organization Environment. The SDK installs context
  only from an authenticated startup or credential-exchange response and omits
  branch/environment selectors on deployed requests. Reserved process
  environment values are backend-written transport and diagnostics, not a
  context activation mechanism. Local Git selection remains repository
  navigation; the SDK derives and inserts any required local wire context
  internally.
- An API is a consumer and composition surface, not hidden producer logic.
- A project CLI command is an executable project interface, not the platform
  permission authority.
- `project_to_agent` exposes verified project CLI workflows as truthful
  project-agent skills; it is not generic Agent administration.
- `AutomaticRedeploymentPolicy` is target-owned and ProjectBranch-scoped. It
  refines the automatic-deployment master switch for one standalone Job,
  ResourceRelease, or Project Coding Agent; it is never a shared
  ProjectBranch-wide rule. A Job policy controls only future qualifying exact
  repository-event promotions and never means a mutable latest image.

Use the platform ontology for global platform nouns. Define the project's own
business concepts inside the Blueprint.

## Preserve The Organization Environment Contract

Read `mainsequence://platform/skills/organization-environments` whenever a
design involves shared data or configuration, exact branch lanes, Project
Executors, environment management, or promotion between environments. That
skill owns the complete cross-platform ontology and lifecycle guidance; do not
reconstruct it from individual Project, MetaTable, Secret, or release rules.

When a Project Blueprint depends on this architecture, record the intended
exact branch lane and environment assumptions in decisions, constraints,
dependencies, and acceptance criteria. Do not add unapproved persisted fields
or a second environment permission system to the Blueprint. Do not add a new
top-level Blueprint environment domain without a separately approved contract.

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

When a component requires process configuration, record the required variable
names, non-secret value intent, target ownership, and secret exclusions in its
existing constraints, decisions, dependencies, and acceptance criteria. The
implementation handoff uses the live `project-workflows` API `2.1.0` template.
Do not add a second Blueprint environment-variable domain or represent a
workflow literal as a platform Secret/Constant resource.

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
- physical schema and unqualified SQLAlchemy table name;
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
- image ownership intent: a caller-selected exact ready image for manual
  pinning, or backend-derived exact image for automatic deployment;
- whether future qualifying repository events may promote the Job to another
  exact image, plus the optional exact-tag regex policy;
- `cpu_request` and `memory_request`;
- optional `gpu_request` and `gpu_type`;
- `spot`;
- positive `max_runtime_seconds`;
- optional `task_schedule` using the existing interval or crontab schedule
  shape, including start-time or one-off intent when needed.

The canonical creation flow infers the Job type from `execution_path` or
`app_name`. Do not declare an independent type or command contract in the
Blueprint.

Direct manual Job creation selects one already-ready exact project image.
Direct automatic Job creation does not accept an image selector: the backend
derives one exact initial image from the ProjectBranch's persisted synchronized
commit and owns its preparation. Workflow Job declarations likewise carry no
image or commit selectors: workflow API `2.1.0` derives the exact image from
the immutable repository event. Neither automatic path resolves branch HEAD at
runtime or persists an image-less Job.

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

When implementation produces a deployable FastAPI, Streamlit, agent-runtime,
static-site, or widget-extension target, hand the accepted release intent to the
`resource-release` execution skill. Do not copy the live ResourceRelease
serializer into the Blueprint.

For a widget-extension deliverable, record only why the project needs the
extension and the repository-relative source ownership needed for
implementation handoff. Do not add a `widgets` top-level Blueprint domain or
copy SDK manifest/instance contracts into project design. The installed
Command Center SDK skill bundle owns the manifest and executable module; the
`project-workflows` and `resource-release` skills own deployment.

For a browser-called FastAPI, record the intended exact or wildcard browser
origins as API deployment intent when the platform default is not sufficient.
Omitted FastAPI creation uses the current platform deployment's static-site
wildcard (`site-dev` in development and `site` in production); this is not an
Organization Environment mapping. The execution handoff uses the FastAPI
release's canonical persisted `cors_allowed_origins`; project code and workflow
`env_vars` do not install or configure platform CORS middleware. A changed
policy requires runtime redeployment before browser CORS headers change.

When an accepted static site calls an accepted FastAPI release through
platform delegation, record the exact source StaticSiteRelease UID, exact
target FastAPI ResourceRelease UID, required target CORS origin policy, and
same-Organization requirement in the connected API/static-site design and
implementation handoff. Do not infer or require a common ProjectBranch,
repository branch, or OrganizationProjectEnvironment. These UIDs are deployed
release identities, not a new persistent Blueprint relationship model; if the
releases do not yet exist, make their later UID resolution an explicit handoff
condition rather than inventing values.

If the accepted runtime release is implemented as an automatically managed
repository workflow, also use `project-workflows`: record source and promotion
intent, but do not design, prebuild, or select `related_image_uid`. The backend
owns image resolution after policy eligibility.

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
- project-agent skills;
- optional accepted deployment intent using `automatic_deployment` and the
  nested `automatic_redeployment_policy.tag_regex`; omit the policy to request
  the generated branch-specific SemVer rule, and use explicit null only when
  every synchronized commit is intended.

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

Project Coding Agent deployment intent never includes a caller-built project
image or Project Executor image. The backend owns both builds; its server-side
target policy owns later automatic-redeployment eligibility.

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
  already accepted;
- optional `deployment.automatic_redeployment_policy.tag_regex` only when the
  promotion rule is accepted; omit it for the backend-generated branch SemVer
  default or use null for every commit; and
- observable acceptance criteria.

When an accepted Static Site must appear in Command Center navigation, record
the intended label, allowlisted icon, enabled state, and recipient category in
that Static Site's constraints and acceptance criteria. The implementation
handoff uses the workflow's nested `navigation_link`; it does not add a
top-level Blueprint links domain. Record that a human grant for the exact
ProjectBranch, workflow path, resource key, and maximum audience is a
precondition. Do not treat repository access, Project edit authority, Git
identity, or the automation identity as audience approval, and do not claim
placement grants target access.

Represent an API dependency through `depends_on`, using its `apis.<key>`
reference. Do not invent a build-environment variable name in project design;
transport configuration belongs to the frontend implementation selected
through the installed Command Center SDK skills.

If the static site will call that API through platform delegation, its API
dependency and constraints must state that implementation resolves the exact
source StaticSiteRelease UID and target FastAPI ResourceRelease UID, configures
the target CORS policy for the source origin, and preserves same-Organization
ownership. Do not add a ProjectBranch or OrganizationProjectEnvironment
co-location constraint. The installed Command Center SDK skills own frontend
credential transport; the Blueprint must not contain tokens or reproduce that
protocol.

Do not put API URLs, environment values, tokens, credentials, provider state,
framework versions, Node versions, output defaults, or a copy of the
ResourceRelease serializer in the Blueprint. The complete installed Command
Center SDK skill bundle owns frontend implementation. The MCP `static-site`
skill reads the canonical live capabilities; the `resource-release` skill owns
the shared creation, configuration, deployment, and deployment-state workflow.

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
      routing_mode: spa
      automatic_deployment: true
      automatic_redeployment_policy:
        tag_regex: null
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
- every delegated static-site-to-FastAPI composition records exact deployed
  source and target release identity resolution, whether the platform CORS
  default or a custom override is intended, and
  same-Organization ownership without inventing an environment co-location
  rule;
- every organization-environment assumption uses an Organization-owned
  environment and backend-resolved ProjectBranch assignment;
- every proposed shared environment requires the same exact repository branch
  name across all participating ProjectBranches;
- static-site deployment intent contains only currently approved canonical
  release fields;
- automatic redeployment intent is target-specific, uses only the nested
  `tag_regex`, and does not invent a trigger mode or client-side evaluator;
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
GitRepository branch discovery is not an MCP tool in the current catalog, and
manual branch creation/import is retired by the ADR-031/ADR-0036 lifecycle.
After bootstrap, only a signed provider push may create a missing ProjectBranch,
and only when the Organization already owns the exact matching environment.
Git does not create that environment or choose a DataSource. No MCP branch
creation/import tool exists. Canonical DRF repository detail returns the owning
logical Project UID; it never computes a branch UID.

This Git-driven lifecycle is deployed. A persisted signed push creates a
missing ProjectBranch only when the Organization already owns the exact
matching Environment. Otherwise the push is ignored and creates no branch. Do
not design manual branch creation/import as an alternative lifecycle.

Choose the public `project_type` deliberately when the design establishes the
primary Project scaffold: `python` or `vite_react`. The immutable value belongs
to the logical Project, and every ProjectBranch under it uses that one type;
never design mixed branch types or a branch-level override. Omission during
Project creation means `python`. Do not invent separate language, framework,
profile, or scaffold version fields. The canonical Project response exposes the derived technology, the
mandatory pinned framework image, and repository/commit-scoped SDK
observations. A Vite Project keeps browser build variables on its
StaticSiteRelease rather than ProjectBranch `env_vars`; its environment owns
MetaTable DataSource routing like every other ProjectBranch. Project creation
does not accept a DataSource selector. The backend resolves the Organization's
canonical production environment and assigns the initial `main` ProjectBranch
to it. The Project stores and exposes no default MetaTables DataSource; managed
MetaTable routing resolves only through the exact ProjectBranch's persisted
Organization Environment. The read-only ProjectBranch
`metatables_data_source` and `metatables_data_source_uid` projections stay in
the public branch contract and reflect the branch Environment's routing
configuration.
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
