---
name: organization-environments
description: Understand, enumerate, design, and review Main Sequence Organization Environments and their lifecycle. Use to resolve visible environment UIDs before human/local Agent discovery; distinguish an Organization Environment from a CodeRepository, CodeRepositoryBranch, Git branch, DataSource, release, or deployment; reason about target-derived runtime scope and shared MetaTables, Secrets, and Constants; and separate code promotion from configuration and data migration.
---

# Main Sequence Organization Environments

Use this skill to understand where an Organization Environment fits in the
Main Sequence platform and how it affects code repository branches, CodeRepository Executors,
data, configuration, and releases.

Read `mainsequence://platform/ontology` first for the currently deployed
platform nouns. Read the platform `code-repository-design` skill when environment
decisions must be recorded in a CodeRepository Blueprint. Read the `resource-release`
skill before creating, configuring, or deploying a ResourceRelease.

## Keep Design Status And Runtime State Separate

The canonical normalization design is
`docs/platform/adr/adr-0036-normalization-of-organization-environment-relation.md`.
ADR-0036 supersedes ADR-031 wherever ADR-031 describes Organization-global
operational resources or nullable operational Environment ownership.

ADR-031 is accepted. All architecture and public-contract decisions in its
Decision Checklist are approved, including:

- an Organization owns its `OrganizationEnvironment` rows;
- every Organization has exactly one production environment;
- an Organization may have any number of additional environments;
- CodeRepositories participate through `CodeRepositoryBranch`;
- CodeRepositoryBranch environment assignment is backend-controlled and derived from
  the Organization plus exact repository branch name;
- an Organization has at most one environment for each exact
  `required_repository_branch`;
- branches from several CodeRepositories may share an environment only when every
  exact branch name matches that environment's immutable required branch;
- exact branch `main` is required by the production environment;
- MetaTables, including external registrations and Connection/DataSource
  imports, belong to exactly one Organization Environment while retaining
  their selected physical DataSource;
- Secrets and Constants belong to exactly one Organization Environment, with
  no Organization-global lookup, shadowing, or effective-union fallback;
- Secrets are discovered directly in their exact Environment; there is no
  CodeRepositoryBranch assignment or allowlist;
- authorized humans retain Organization-wide multi-environment discovery and
  explicit environment filters, while Organization-admin permission controls
  environment mutations;
- environment-owned DataSource routing for platform-managed MetaTables and
  environment-wide MetaTable deletion protection add no DataSource-deletion
  blocker;
- exact Git `main` import and synchronization remain independent of
  environment names, and ordinary PATCH cannot rename repository branches;
- signed Git branch push is the only accepted post-bootstrap CodeRepositoryBranch
  creation trigger;
- a pre-created Organization Environment is the exact branch allowlist, and a
  push never creates an environment or chooses a DataSource;
- manual repository branch import and all manual branch-creation helpers are
  retired without a compatibility path, while branch discovery remains
  read-only;
- established mappings change only through explicit migration workflows;
- CodeRepository Executor environment scope is derived through its persisted
  CodeRepositoryBranch; and
- Astro Orchestrator runtime scope is derived through its authenticated
  `UserOrchestratorAgentService` and required Environment-owned Agent;
- deployed SDK callers never set runtime mode, CodeRepositoryBranch, repository
  branch, or environment context: authenticated JobRun startup or runtime
  credential exchange installs backend-derived context, reserved environment
  values alone are non-authoritative, and branch-sensitive requests omit
  caller selection; and
- the canonical environment-management resource is
  `/api/v1/organization-environments/` through an
  `OrganizationEnvironmentViewSet`.

The strict normalization implementation is deployed in Django source: the canonical
DRF relation, shared resolver contract, direct/derived/projected/snapshot model
roles, exact-environment query boundaries, and deterministic data migrations
are present. Public Secret, Constant, MetaTable, Namespace, Scheduler, Agent,
capability, Workspace, widget-group, Bucket, and branch-owned paths now require
or derive one exact Environment. After deterministic resolution, ambiguous
legacy operational rows are retired and every stored Environment FK is
database-enforced `NOT NULL`. This catalog migration moves no physical table
data.

Git-driven creation of a missing CodeRepositoryBranch is deployed. A persisted signed
push provisions the branch only after an exact Environment matching its
repository branch exists; otherwise it records ignored reason
`organization_environment_not_configured` and creates nothing. Manual branch
creation/import is not part of the lifecycle.

Established DataSource, branch, environment, and resource remapping remains a
separate explicit migration operation; ordinary PATCH never performs it.
The registered read-only `organization_environment.list` MCP tool exposes the
canonical DRF collection so a human or local agent can resolve visible
environment names and public UIDs. It does not expose environment creation,
mutation, deletion, branch assignment, or data migration.

## Understand The Accepted Normalization Target

Platform ADR-0036, `Normalization of Organization Environment Relation`, is
accepted and its strict normalization implementation is deployed in the backend
source. It extends the Environment ontology across the whole platform and
supersedes ADR-031's operational global fallback rules. The migration audit is
now a drift guard over the enforced strict database contract.

The normalized ontology has one semantic relation:

```text
organization_environment
organization_environment_uid
?organization_environment_uid=<uid>
```

Every tenant-owned operational object resolves exactly one Environment under
that name. The relation is implemented according to the object's role:

- independently creatable operational roots store a required immutable FK;
- descendants derive it through one mandatory normalized parent;
- declared polymorphic/query boundaries store a backend-maintained read-only
  projection;
- retained history stores an immutable snapshot; and
- identity, physical infrastructure, platform definitions, and deliberately
  multi-environment aggregates explicitly report the relation as not
  applicable rather than exposing a nullable fake Environment.

Do not add the FK to every model and do not add it to `CreatedByMixin`.
Creator/Organization ownership and Environment partitioning are different
concerns. A descendant such as `MetaTableColumn` derives through `MetaTable`;
an independently creatable root such as `Namespace` stores the relation.

The target model by application is:

```text
pod_manager
├── CodeRepositoryBranch -> exact Environment partition
│   └── Jobs, images, releases, runtimes, and CodeRepository Coding Agents derive or
│       carry declared read-only projections/snapshots
├── Secret, Constant, Bucket, and PVCDisk -> direct Environment
└── CodeRepository, DataSource, CloudTenancy, Cluster, registries -> not singular

ts_manager
├── MetaTable, Namespace, Scheduler, TableUpdateNode -> direct Environment
└── columns, indexes, foreign keys, TimeIndexTableUpdate updates -> derive through
    their mandatory MetaTable/update-graph parent

agents
├── Agent, AgentCapability, CodingAgentDeploymentDefault -> direct Environment
├── UserOrchestratorAgentService -> derives through its required Agent; exactly
│   one independently deployed Astro Agent/service per responsible User and
│   Environment pair
├── CodeRepositoryExecutorRuntimeImage and CodeRepositoryExecutorRun -> inherited projection
    or snapshot from their Pod Manager parent
└── sessions, tasks, messages, handles, and bindings -> derive and must match

command_center
├── Workspace and SavedWidgetGroup -> direct Environment
├── workspace/widget/navigation/publication descendants -> derive and match
└── ConnectionInstance and ConnectionHealthCheck -> Organization control-plane,
    not a Secret fallback and not singular to one Environment
```

Every relation connecting two environment-related objects must resolve the
same exact Environment, even when both objects belong to the same
Organization. Organization equality is necessary but not sufficient.

ADR-0036 removes the product concept of Organization-global operational
Secrets, Constants, and MetaTables. New public writes and collection semantics
require one exact Environment; there is no environment-over-global shadowing
or effective union lookup. Existing ambiguous operational rows that cannot be
resolved from exact ownership evidence are deleted rather than retained as
nullable migration debt. The local `org_test_<organization>` credential has an
explicit production-Environment rule; it is not a general fallback. Use
`audit_organization_environments --strict` as the ongoing drift guard. Do not
describe nullable operational columns or legacy Secret/Constant `scope` values
as supported behavior.

## Place The Environment In The Platform Ontology

An Organization Environment is the canonical Organization-wide operational
partition for data, configuration, execution, applications, and agents. It is
not a child of one CodeRepository.

For CodeRepository-owned resources, the exact Git branch is the repository-side
partition marker and `CodeRepositoryBranch` is the durable platform marker that binds
one logical CodeRepository to exactly one Environment. This is the platform's
multi-environment composition model: a CodeRepository spans environments through
sibling CodeRepositoryBranches, while every branch-owned descendant stays inside the
partition resolved by its exact CodeRepositoryBranch.

```text
Organization
├── OrganizationEnvironment
│   ├── MetaTable (managed or external)
│   ├── Secret
│   ├── Constant
│   ├── Namespace, Scheduler, and TableUpdateNode
│   ├── Bucket and PVCDisk
│   ├── Agent and AgentCapability
│   ├── UserOrchestratorAgentService through its Environment-owned Agent
│   └── Workspace and SavedWidgetGroup
└── CodeRepository
    ├── GitHubRepositoryBinding
    └── CodeRepositoryBranch ──> OrganizationEnvironment
        ├── ResourceRelease
        ├── Job
        └── UserCodeRepositoryExecutorAgentService
```

Several CodeRepositories in the same Organization can therefore use one environment.
They do so through compatible branches, not through a CodeRepository-to-environment
membership row.

## Distinguish The Identities

| Concept | Stable meaning | It does not mean |
| --- | --- | --- |
| `Organization` | Tenant and owner of environments and Organization control-plane resources | One deployment stage or a fallback operational environment |
| `OrganizationEnvironment` | Canonical Organization-wide operational partition | A CodeRepository, Git branch, DataSource, release, or deployment |
| `CodeRepository` | Logical code repository aggregate that owns its branches, source link, sharing, labels, and lifecycle | The active environment or execution branch |
| `GitHubRepositoryBinding` | Provider/source-control identity | An environment or selected CodeRepositoryBranch |
| `CodeRepositoryBranch` | Durable CodeRepository participation marker and execution context for one exact provider branch and Environment partition | A caller-selected environment mapping |
| `repository_branch` | Exact, case-sensitive repository-side partition marker used for backend assignment | Environment identity, authorization, or display name |
| `DataSource` | Physical database connection identity | The logical environment or proof of data ownership |
| `MetaTable` | Catalog identity for one physical table | A CodeRepository-owned environment selector |
| `ResourceRelease` | Durable deployable target owned by one CodeRepositoryBranch | An environment, promotion lane, or deployment attempt |
| `DeploymentRun` | One deployment attempt for a target | The environment or durable release configuration |
| `UserCodeRepositoryExecutorAgentService` | Deployed CodeRepository Executor service tied to one CodeRepositoryBranch | A human-selectable active environment |

The environment has its own public UID and operator-facing name. Its
`required_repository_branch` is an immutable branch-compatibility and backend
assignment rule; it is not the environment identity. Its
`metatables_data_source` is physical routing configuration; it is also not the
environment identity.

For deployed code-repository code, follow the ownership chain, never process input:
`JobRun -> Job -> CodeRepositoryBranch`, `UserCodeRepositoryExecutorAgentService ->
CodeRepositoryBranch`, or runtime `ResourceRelease -> CodeRepositoryBranch`. The backend
derives the Organization Environment through that CodeRepositoryBranch. SDK methods
do not accept a runtime/branch/environment override. A genuine local checkout
may change Git branches, but the SDK translates the current checkout to a
persisted CodeRepositoryBranch internally only when constructing an authorized wire
request; that is local discovery, not runtime selection.

Environment display names are Organization-defined. Do not prescribe a fixed
`main`/`dev` pair or any fixed number of environments. Only the production
environment's required repository branch is fixed to exact `main`.

## Preserve The Branch Compatibility Rule

CodeRepository creation always establishes production `main`. It may accept a visible
`bootstrap_organization_environment_uid` as creation context. The backend derives that
Environment's exact required branch and, when non-main, creates its provider ref from
the initialized main commit. The caller never chooses a branch or branch foreign key.
After this bootstrap, the provider supplies any missing branch through a signed push.

The target backend resolution is:

```text
(CodeRepository.organization_owner, CodeRepositoryBranch.repository_branch)
    -> OrganizationEnvironment.required_repository_branch
```

The approved Organization/required-branch uniqueness rule makes this lookup
deterministic. Two environments in the same Organization cannot claim the same
exact required repository branch.

The resolved relationship must satisfy:

```text
CodeRepository.organization_owner == Environment.organization_owner

AND

CodeRepositoryBranch.repository_branch == Environment.required_repository_branch
```

`CodeRepositoryBranch.organization_environment` is persisted but read-only
and backend-controlled. Reject a caller-supplied Environment UID on branch create or
update; the distinct CodeRepository-create bootstrap context remains allowed. Do not fall
back to production when the exact non-production branch has no configured
environment.

Treat `required_repository_branch` as an administrator-controlled allowlist.
The environment must exist before the push. When it does not, processing uses
ignored reason `organization_environment_not_configured` and creates nothing.
Never infer that Git is authorized to create the missing environment.

Branches from different CodeRepositories may share one environment only when all of
these are true:

1. every CodeRepository belongs to the same Organization as the environment;
2. every branch has the same exact, case-sensitive `repository_branch`; and
3. that branch value equals the environment's
   `required_repository_branch`.

Similar purpose, the same DataSource, or similar branch spelling is not enough.
Changing the environment display name must not change this mapping. Changing a
branch or required-branch mapping is a transition workflow, not ordinary
PATCH.

## Understand The Caller Context

### Branch-Owned Kubernetes Runtime

A deployed JobRun, CodeRepository Executor, or runtime ResourceRelease has a
trustworthy implicit branch context because the authenticated backend target
already owns exactly one CodeRepositoryBranch:

```text
JobRun runtime JWT -> JobRun -> Job -> CodeRepositoryBranch -> Environment

runtime credential -> UserCodeRepositoryExecutorAgentService
                   -> CodeRepositoryBranch -> Environment

runtime credential -> ResourceRelease -> CodeRepositoryBranch -> Environment
```

The startup or credential-exchange response supplies the same public
`runtime_code_repository_context` for each branch-owned target. The request cannot
choose or widen the derived branch or environment. Environment scope must
refine existing organization, object, capability, billing, and operation
authorization; it never replaces those checks. Container environment values
and image provenance assist SDK initialization and diagnostics but do not
replace backend authentication as the authority.

Every runtime JWT also authenticates one persisted responsible User. Normal
DRF, role, service-identity, object, and operation policy decides which actions
that User may perform regardless of token scope. The branch/environment chain
narrows which resources compose the result; it does not maintain a parallel
action allowlist.

### Human Or Local Coding Agent

A human JWT or local coding agent has no implicit authenticated CodeRepositoryBranch.
Before Agent list or search, call `organization_environment.list`, present the
visible environment names, required repository branches, production role, and
public UIDs, and ask the user which environment should bound the work. Continue
limit/offset pagination until `next` is null before presenting the choice set.
If the user already named one, still resolve it through the tool instead of
guessing its UID. Do not default to production or silently choose the only
row. Reuse the selected UID for the bounded workflow and pass it explicitly to
every `agent.list` or `agent.search` call.

The same explicit selection also bounds human coding-agent service,
AgentSession, and AgentTask collections. Apply it before every other filter,
search, ordering, count, or pagination operation. Do not merge rows by Agent
display name: one User may have an `Astro` Agent and a separately deployed
`UserOrchestratorAgentService` in each visible Environment. Astro deploy uses
top-level `organization_environment_uid`; `scope.kind=user` identifies the
responsible principal only and is never a complete deployment, reconciliation,
cache, or runtime identity.

A genuine local checkout may use its active Git branch only to discover a
persisted CodeRepositoryBranch for an explicit operation; it cannot turn that
discovery into a runtime credential or infer an environment directly. Do not
infer an active environment from a CodeRepository, DataSource, production default,
branch text alone, or request body.

### Environment-Owned And Other Coding-Agent Services

Do not give an Organization test runtime or an unapproved coding-agent service
type Environment semantics merely because it belongs to the same Organization.
Only a persisted authenticated target relationship creates implicit runtime
context. A missing or inconsistent runtime Environment must fail with `403` and
must not fall back to human grants, production, `main`, an image, or a
DataSource.

An Astro runtime credential is still Environment-scoped even though it has no
CodeRepositoryBranch. Its exact chain is runtime credential to
`UserOrchestratorAgentService` to required Agent to Organization Environment.
It may use only that exact service/Agent/session boundary and must never be
combined with an endpoint, token, or service UID cached for another
Environment.

## Understand The Resource Boundary

### MetaTables

Platform-managed MetaTables belong directly to one Organization Environment.
External-registered MetaTables, including Connection/DataSource imports, also
belong to one explicit same-Organization Environment while retaining their
selected physical DataSource.

A non-empty logical `identifier` is unique within its Environment. Public UID
lookup remains exact and still enforces the same Environment boundary.

For a CodeRepository Executor in environment `E`, scope must be applied before list,
retrieve, search, identifier lookup, registration, import, reservation,
finalization, or write. Its effective set is exactly rows in `E`; rows in every
other environment are excluded. Filtering only
a collection response is not isolation: a known UID must obey the same rule.

Platform-managed work uses the environment routing DataSource. External rows
retain their selected Connection/DataSource even when an environment is
attached. Physical table identity remains separate and globally unique by
Organization/DataSource/schema/table across all MetaTable scopes.

### Secrets And Constants

Every operational Secret and Constant belongs to exactly one Organization
Environment. There is no Organization-global scope, environment-over-global
shadowing, or effective union. Public writes require
`organization_environment_uid`; list, retrieve, and name resolution
are constrained to that exact Environment.

Legacy rows without deterministic evidence are deleted during strict cutover.
They are never exposed as global resources or retained without an Environment.

Do not confuse those platform configuration resources with workflow API
`2.0.0` `env_vars`. A workflow literal is target-owned process configuration
stored on one Job or one runtime target's backing Job. It does not perform
Secret or Constant name resolution, create a Secret or Constant, select
an Organization Environment, or change CodeRepositoryBranch assignment. The branch's
backend-derived environment remains the authorization and discovery boundary;
the literal only reaches the target process after its normal deployment path.

Resources from another Environment are not eligible. Same-Environment logical
duplicates remain conflicts. Public-UID lookup remains exact and never
substitutes a same-name row.

Environment membership is not Secret injection. Secret value access keeps its
stronger authorization, and no branch assignment or alias layer grants runtime access.

### CodeRepository Coding Agents

Agent list, quick-search, and semantic-search require one
`organization_environment_uid`. Apply this boundary before filtering
or ranking and return only typed CodeRepository Coding Agents whose persisted
CodeRepositoryBranches belong to that environment. This permits discovery across
CodeRepositories only when the exact branches share the same Organization Environment.
CodeRepository Coding Agents from every other environment and unscoped Agent types are
excluded.

An authorized human or local caller first uses
`organization_environment.list`, presents the visible choices to the user,
and asks which environment should bound the work. The selected public UID is
then required on `agent.list` and `agent.search`. A deployed Astro Orchestrator
or CodeRepository Executor does not list or choose environments: Django derives
the exact Environment from the authenticated service target, while Astro Tau
removes the selector from the model-visible MCP schema. Never ask a deployed
coding-agent runtime user to select an environment, and never
infer or widen scope from Organization membership, repository branch text,
DataSource equality, or prompt input.

Same-environment discovery does not grant arbitrary session access. Astro and
executor runtimes may delegate only to a typed CodeRepository Executor in the
same Environment. Delegation requires a caller-owned parent session, and the
persisted parent-child relationship authorizes subsequent delegated runtime-
access and task operations. Runtime-managed subagent bindings require a typed
CodeRepository Executor child in the same environment, and the calling runtime
may manage only its own outbound bindings.

### DataSource

The environment DataSource selects where future platform-managed
MetaTable-oriented work is routed. It does not override the selected
Connection/DataSource of an external registration, define environment identity,
or prove that existing MetaTables or physical data belong to the environment.

Deleting a DataSource receives no new blocker merely because an environment
references it. Environment-wide MetaTable deletion protection protects tables,
not the DataSource record.

### Jobs, Releases, And CodeRepository Executors

Jobs, ResourceReleases, and CodeRepository Executor services remain owned by an exact
CodeRepositoryBranch. They do not move under the Organization Environment. The branch
links them to their environment context. Their code-repository images must carry
verified source provenance for the same exact CodeRepositoryBranch and commit. At
runtime, backend authentication derives and issues the CodeRepositoryBranch context;
a deployed SDK does not inspect Git or use image provenance as runtime
ownership.

## Understand The Approved Management Surface

The canonical environment-management resource is approved as:

```text
OrganizationEnvironmentViewSet(ModelViewSet)
/api/v1/organization-environments/
```

This establishes one Organization-level collection/detail resource rather than
an endpoint nested below each CodeRepository. Public lookup uses the environment UID.
The ADR defines list, create, retrieve, partial-update, and delete intent and
does not define full-replacement PUT.

The route is deployed with the accepted serializer fields, filters,
Organization-admin mutation permissions, and transition restrictions.
Authenticated coding-agent runtime credentials can observe only their
target-derived environment and cannot mutate this resource. The read-only
`organization_environment.list` MCP tool
delegates to this exact list action and returns its canonical paginated
serializer response. It adds no MCP-only visibility or permission rule.

## Follow The Environment Lifecycle

### 1. Organization Bootstrap

Organization provisioning creates exactly one production environment. Its
persisted production role is backend-controlled,
and its required repository branch is exact `main`. The display name may be
`production`; behavior must not depend on comparing that name.

### 2. Additional Environment Creation

An Organization administrator may define any number of additional environments
with distinct names and exact required repository branches. Creating an
environment establishes a resource boundary and branch lane. It does not create
a CodeRepository, provider branch, DataSource, table, Secret, release, or deployment.

### 3. CodeRepository And Initial Branch Creation

Canonical CodeRepository creation creates the logical CodeRepository and initial exact
production `main` CodeRepositoryBranch. Optional
`bootstrap_organization_environment_uid` selects one visible Environment context; a
non-main Environment causes the backend to create its derived branch from main. A
caller without Production visibility does not receive a Production grant.

### 4. Signed Provider Branch Push

After the Organization administrator creates the environment that allows the
exact branch, a signed provider push idempotently creates the missing sibling
CodeRepositoryBranch under the same logical CodeRepository and then runs canonical repository
reconciliation. Missing environment configuration produces ignored reason
`organization_environment_not_configured`; it does not silently use production
and creates nothing.

The push does not copy environment resources, Secrets, Jobs, releases,
deployments, runtime history, or physical data. It never creates the
environment or selects its DataSource. Delivery replay and concurrent pushes
must converge on one `(code_repository, repository_branch)` row.

The deployed lifecycle has no manual repository `import-branch` action or
manual branch-creation helper. Read-only provider branch discovery remains.

### 5. CodeRepository Executor Deployment And Runtime

CodeRepository Coding Agent preparation remains repository work owned by the
`code-repository-to-agent` skill. Deployment creates or reconciles the canonical
CodeRepositoryBranch-owned CodeRepository Executor target and service. Under the environment
design, authenticated CodeRepository Executor platform operations derive data and
configuration scope through the persisted service-to-branch-to-environment
chain.

Environment selection is not a deployment input and must not be stored again
on the service as a caller-editable field.

### 6. Code Promotion And Release Deployment

Environment lifecycle and release lifecycle are different:

```text
Git commit or exact-commit tag
  -> synchronize one exact CodeRepositoryBranch
  -> evaluate each target-owned automatic redeployment policy
  -> deploy the CodeRepositoryBranch-owned ResourceRelease or CodeRepository Coding Agent
  -> create or reuse canonical DeploymentRun history

CodeRepositoryBranch
  -> OrganizationEnvironment
  -> data and configuration context
```

The environment itself is not deployed and owns no DeploymentRun.

To promote code toward another environment, the user's Git/CI workflow moves
the code to the exact provider branch required by the target environment. The
platform then synchronizes that target CodeRepositoryBranch and follows its normal
release policy. Do not promote code by rewriting
`CodeRepositoryBranch.organization_environment`.

Automatic promotion remains target-owned:

- `automatic_deployment=false` disables repository-triggered promotion for
  that target;
- `automatic_deployment=true` with a null policy regex allows every
  synchronized commit;
- a non-null policy regex requires a matching tag on the exact synchronized
  commit;
- the generated default uses stable SemVer for exact `main` and a
  branch-qualified SemVer pattern for every other actual branch; and
- explicit deployment and same-revision repair remain separate from automatic
  source-promotion eligibility.

Use the `resource-release` skill for the callable release and DeploymentRun
workflow. Do not invent an environment-level release or generic promotion
operation.

### 7. Configuration And Data Promotion

Deploying code does not copy or move:

- physical schemas or tables;
- MetaTable registrations;
- history, TimeIndexTableUpdater progress, or checkpoints;
- Secrets or Constants;
- Jobs, schedules, releases, or deployment provenance; or
- DataSource or Alembic ownership.

Configuration promotion means explicitly creating or selecting the intended
target-Environment resources under the approved authorization model.
Data promotion requires a separately approved preflight and explicit copy,
move, reuse, archive, or reject policy. Do not represent either operation as an
environment FK PATCH.

### 8. Environment Reconfiguration Or Retirement

Changing an established DataSource, required branch, branch assignment,
MetaTable environment, or Secret/Constant scope can change visibility and
routing without moving underlying state. Stop at the migration gate until a
separate transition workflow defines inventory, conflicts, quiescence,
authorization, rollback, and partial-failure recovery.

The accepted management contract prevents deleting production, referenced, or
non-empty environments. An unused non-production environment may be retired
only through the canonical Organization-admin operation after that contract is
deployed.

## Example With Several Environments

```text
Organization: Acme

Environment "production"
  is_production = true
  required_repository_branch = main

Environment "research"
  required_repository_branch = research

Environment "candidate-eu"
  required_repository_branch = release/candidate
```

CodeRepository Alpha branch `research` and CodeRepository Beta branch `research` may share
the `research` environment. CodeRepository Beta branch `release/candidate` belongs to
`candidate-eu`, not `research`. A DataSource shared by both environments would
not merge their logical table or configuration identities.

Constant `runtime/LOOKBACK_DAYS` for `research` is a different
Environment-owned resource from a same-named Constant in production. A CodeRepository
Executor resolves only the row in its exact Environment.

A release for CodeRepository Alpha branch `research` deploys that branch's persisted
current commit. It does not deploy the `research` environment and does not copy
research data into production.

## Route Work To The Correct Skill

- Use `code-repository-design` to record why a CodeRepository uses particular exact branch
  lanes and which environment assumptions affect MetaTables, TimeIndexTableUpdaters, Jobs,
  APIs, CLI commands, code-repository-agent behavior, and static sites.
- Use `code-repository-to-agent` to prepare truthful repository instructions, skills,
  and the source card for a CodeRepository Coding Agent.
- Use `resource-release` to discover, configure, deploy, and observe a
  CodeRepositoryBranch-owned ResourceRelease.
- Use `organization_environment.list` before human/local Agent discovery to
  resolve visible environment names to public UIDs and obtain the user's
  explicit environment selection.
- Use `static-site` for the static-site specialization after the exact
  CodeRepositoryBranch is selected.
- Stop for a separately approved data-migration workflow when the requested
  action would move or reassign established environment state.

Do not add a new top-level CodeRepository Blueprint domain for environments. Record
environment assumptions in decisions, dependencies, constraints, and
acceptance criteria until a separately approved Blueprint contract says
otherwise.

## Stop Conditions

Stop and ask for direction when:

- the Organization, logical CodeRepository, exact CodeRepositoryBranch, and environment are
  being treated as one identity;
- a caller tries to select or PATCH the CodeRepositoryBranch environment directly;
- branches with different exact names are assigned to one environment;
- a human or generic coding-agent credential is treated as having an implicit
  branch environment;
- a release operation is described as deploying an environment;
- code deployment is assumed to migrate data or configuration;
- an established environment mapping would change without preflight and a
  migration policy;
- the request needs an environment mutation or detail operation that is absent
  from the registered MCP catalog.

## Handoff

Return:

1. the Organization and exact CodeRepositoryBranch identities involved;
2. the environment's role, required branch, and affected resource classes;
3. the caller context and whether environment scope is implicit or explicit;
4. whether the request changes code, deployment, configuration, data, or an
   environment mapping;
5. the applicable accepted ADR-031 rule and any separately required migration
   design; and
6. the next owning skill or canonical application workflow.
