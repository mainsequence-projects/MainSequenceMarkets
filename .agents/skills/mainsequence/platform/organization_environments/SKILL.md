---
name: organization-environments
description: Understand, enumerate, design, and review Main Sequence Organization Environments and their lifecycle. Use to resolve visible environment UIDs before human/local Agent discovery; distinguish an Organization Environment from a Project, ProjectBranch, Git branch, DataSource, release, or deployment; reason about branch-owned runtime scope and shared MetaTables, Secrets, and Constants; and separate code promotion from configuration and data migration.
---

# Main Sequence Organization Environments

Use this skill to understand where an Organization Environment fits in the
Main Sequence platform and how it affects project branches, Project Executors,
data, configuration, and releases.

Read `mainsequence://platform/ontology` first for the currently deployed
platform nouns. Read the platform `project-design` skill when environment
decisions must be recorded in a Project Blueprint. Read the `resource-release`
skill before creating, configuring, or deploying a ResourceRelease.

## Keep Design Status And Runtime State Separate

The canonical design is
`docs/tdag/pod_manager/adr/adr-031-organization-project-environment-management.md`.

ADR-031 is accepted. All architecture and public-contract decisions in its
Decision Checklist are approved, including:

- an Organization owns its `OrganizationProjectEnvironment` rows;
- every Organization has exactly one production environment;
- an Organization may have any number of additional environments;
- Projects participate through `ProjectBranch`;
- ProjectBranch environment assignment is backend-controlled and derived from
  the Organization plus exact repository branch name;
- an Organization has at most one environment for each exact
  `required_repository_branch`;
- branches from several Projects may share an environment only when every
  exact branch name matches that environment's immutable required branch;
- exact branch `main` is required by the production environment;
- platform-managed MetaTables are direct children of their Organization
  Environment;
- external-registered MetaTables, including Connection/DataSource imports, may
  be Organization-scoped or explicitly environment-scoped;
- Project Executor MetaTable discovery composes Organization-scoped external
  rows with rows from its branch environment and excludes other environments;
- Secrets and Constants support `global` and `environment` scope;
- existing Secret and Constant rows migrate to `global` scope;
- a branch's effective resources compose Organization-global resources with
  resources from its backend-derived environment, excluding other
  environments;
- environment scope wins over global scope during name-based resolution while
  public-UID lookup remains exact;
- Secret and Constant creation supports non-mutating cross-scope shadowing
  preflight warnings;
- `ProjectSecret` accepts Organization-global Secrets and Secrets from the
  branch's own environment, never another environment;
- authorized humans retain Organization-wide multi-environment discovery and
  explicit environment filters, while Organization-admin permission controls
  environment mutations;
- environment-owned DataSource routing for platform-managed MetaTables and
  environment-wide MetaTable deletion protection add no DataSource-deletion
  blocker;
- exact Git `main` import and synchronization remain independent of
  environment names, and ordinary PATCH cannot rename repository branches;
- signed Git branch push is the only accepted post-bootstrap ProjectBranch
  creation trigger;
- a pre-created Organization Environment is the exact branch allowlist, and a
  push never creates an environment or chooses a DataSource;
- manual repository branch import and all manual branch-creation helpers are
  retired without a compatibility path, while branch discovery remains
  read-only;
- established mappings remain blocked until a separate migration workflow;
- Project Executor environment scope is derived through its persisted
  ProjectBranch; and
- deployed SDK callers never set runtime mode, ProjectBranch, repository
  branch, or environment context: authenticated JobRun startup or runtime
  credential exchange installs backend-derived context, reserved environment
  values alone are non-authoritative, and branch-sensitive requests omit
  caller selection; and
- the canonical environment-management resource is
  `/api/v1/organization-project-environments/` through an
  `OrganizationProjectEnvironmentViewSet`.

The implementation is deployed in Django: the environment model and production
bootstrap, ProjectBranch assignment, canonical DRF
ViewSet, MetaTable and resource scoping, Project Executor runtime derivation,
Secret/Constant preflights, Job routing, and Git `main` import rule are active.
Platform-managed MetaTables have a non-null environment. External registrations
may have a null environment and therefore remain Organization-scoped. The
schema rollout retains production assignment for existing platform-managed
rows and migrates existing external registrations to Organization scope. This
catalog migration moves no physical table data.

Do not confuse accepted design with deployed behavior. Git-driven creation of
a missing ProjectBranch is approved but not deployed yet: current webhook
processing synchronizes only an existing ProjectBranch and ignores an unknown
branch, while the manual repository `import-branch` action still exists. The
accepted cutover makes the signed push provision the branch only after an
exact environment exists, then removes that action and its manual helpers in
the same deployment.

Established DataSource, branch, environment, and resource remapping remains
blocked because no data-migration workflow has been designed or approved.
The registered read-only `organization_environment.list` MCP tool exposes the
canonical DRF collection so a human or local agent can resolve visible
environment names and public UIDs. It does not expose environment creation,
mutation, deletion, branch assignment, or data migration.

## Place The Environment In The Platform Ontology

An Organization Environment is the Organization-wide data and configuration
boundary used by compatible ProjectBranches. It is not a child of one Project.

```text
Organization
├── Organization-scoped external MetaTable
├── OrganizationProjectEnvironment
│   ├── platform-managed MetaTable
│   ├── environment-scoped external MetaTable
│   ├── environment-scoped Secret
│   └── environment-scoped Constant
├── Organization-global Secret and Constant
└── Project
    ├── GitRepository
    └── ProjectBranch ──> OrganizationProjectEnvironment
        ├── ResourceRelease
        ├── Job
        └── UserProjectExecutorAgentService
```

Several Projects in the same Organization can therefore use one environment.
They do so through compatible branches, not through a Project-to-environment
membership row.

## Distinguish The Identities

| Concept | Stable meaning | It does not mean |
| --- | --- | --- |
| `Organization` | Tenant and owner of environments and Organization-scoped resources | One deployment stage |
| `OrganizationProjectEnvironment` | Organization-wide resource and execution context | A Project, Git branch, DataSource, release, or deployment |
| `Project` | Logical project aggregate that owns its branches, source link, sharing, labels, and lifecycle | The active environment or execution branch |
| `GitRepository` | Provider/source-control identity | An environment or selected ProjectBranch |
| `ProjectBranch` | Durable configuration and execution context for one exact provider branch | A caller-selected environment mapping |
| `repository_branch` | Exact, case-sensitive provider branch name | Environment identity or display name |
| `DataSource` | Physical database connection identity | The logical environment or proof of data ownership |
| `MetaTable` | Catalog identity for one physical table | A Project-owned environment selector |
| `ResourceRelease` | Durable deployable target owned by one ProjectBranch | An environment, promotion lane, or deployment attempt |
| `DeploymentRun` | One deployment attempt for a target | The environment or durable release configuration |
| `UserProjectExecutorAgentService` | Deployed Project Executor service tied to one ProjectBranch | A human-selectable active environment |

The environment has its own public UID and operator-facing name. Its
`required_repository_branch` is an immutable branch-compatibility and backend
assignment rule; it is not the environment identity. Its
`metatables_data_source` is physical routing configuration; it is also not the
environment identity.

For deployed project code, follow the ownership chain, never process input:
`JobRun -> Job -> ProjectBranch`, `UserProjectExecutorAgentService ->
ProjectBranch`, or runtime `ResourceRelease -> ProjectBranch`. The backend
derives the Organization Environment through that ProjectBranch. SDK methods
do not accept a runtime/branch/environment override. A genuine local checkout
may change Git branches, but the SDK translates the current checkout to a
persisted ProjectBranch internally only when constructing an authorized wire
request; that is local discovery, not runtime selection.

Environment display names are Organization-defined. Do not prescribe a fixed
`main`/`dev` pair or any fixed number of environments. Only the production
environment's required repository branch is fixed to exact `main`.

## Preserve The Branch Compatibility Rule

Project creation establishes `main`. After bootstrap, the provider supplies an
exact branch through a signed push; a human caller chooses neither the branch
creation operation nor the environment foreign key.

The target backend resolution is:

```text
(Project.organization_owner, ProjectBranch.repository_branch)
    -> OrganizationProjectEnvironment.required_repository_branch
```

The approved Organization/required-branch uniqueness rule makes this lookup
deterministic. Two environments in the same Organization cannot claim the same
exact required repository branch.

The resolved relationship must satisfy:

```text
Project.organization_owner == Environment.organization_owner

AND

ProjectBranch.repository_branch == Environment.required_repository_branch
```

`ProjectBranch.organization_project_environment` is persisted but read-only
and backend-controlled. Reject a caller-supplied environment UID. Do not fall
back to production when the exact non-production branch has no configured
environment.

Treat `required_repository_branch` as an administrator-controlled allowlist.
The environment must exist before the push. When it does not, processing uses
ignored reason `organization_environment_not_configured` and creates nothing.
Never infer that Git is authorized to create the missing environment.

Branches from different Projects may share one environment only when all of
these are true:

1. every Project belongs to the same Organization as the environment;
2. every branch has the same exact, case-sensitive `repository_branch`; and
3. that branch value equals the environment's
   `required_repository_branch`.

Similar purpose, the same DataSource, or similar branch spelling is not enough.
Changing the environment display name must not change this mapping. Changing a
branch or required-branch mapping is a transition workflow, not ordinary
PATCH.

## Understand The Caller Context

### Branch-Owned Kubernetes Runtime

A deployed JobRun, Project Executor, or runtime ResourceRelease has a
trustworthy implicit branch context because the authenticated backend target
already owns exactly one ProjectBranch:

```text
JobRun runtime JWT -> JobRun -> Job -> ProjectBranch -> Environment

runtime credential -> UserProjectExecutorAgentService
                   -> ProjectBranch -> Environment

runtime credential -> ResourceRelease -> ProjectBranch -> Environment
```

The startup or credential-exchange response supplies the same public
`runtime_project_context` for each branch-owned target. The request cannot
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

A human JWT or local coding agent has no implicit authenticated ProjectBranch.
Before Agent list or search, call `organization_environment.list`, present the
visible environment names, required repository branches, production role, and
public UIDs, and ask the user which environment should bound the work. Continue
limit/offset pagination until `next` is null before presenting the choice set.
If the user already named one, still resolve it through the tool instead of
guessing its UID. Do not default to production or silently choose the only
row. Reuse the selected UID for the bounded workflow and pass it explicitly to
every `agent.list` or `agent.search` call.

A genuine local checkout may use its active Git branch only to discover a
persisted ProjectBranch for an explicit operation; it cannot turn that
discovery into a runtime credential or infer an environment directly. Do not
infer an active environment from a Project, DataSource, production default,
branch text alone, or request body.

### Organization-Scoped And Other Coding-Agent Services

Do not give an Organization orchestrator, test runtime, or another coding-agent
service type branch-owned semantics merely because it belongs to the same
Organization. Only a persisted target relationship to a ProjectBranch creates
implicit branch context. A null runtime context is intentional and must not
fall back to production, `main`, an image, or a DataSource.

## Understand The Resource Boundary

### MetaTables

Platform-managed MetaTables belong directly to one Organization Environment.
External-registered MetaTables, including Connection/DataSource imports, may
instead have a null environment and remain Organization-scoped, or may be
attached to one same-Organization environment.

A non-empty logical `identifier` is unique within its environment, or within
the Organization for a null-environment row. Environment-aware name resolution
prefers an environment row and falls back to the Organization-scoped external
row. Public UID lookup remains exact.

For a Project Executor in environment `E`, scope must be applied before list,
retrieve, search, identifier lookup, registration, import, reservation,
finalization, or write. Its effective set is Organization-scoped external rows
plus rows in `E`; rows in every other environment are excluded. Filtering only
a collection response is not isolation: a known UID must obey the same rule.

Platform-managed work uses the environment routing DataSource. External rows
retain their selected Connection/DataSource even when an environment is
attached. Physical table identity remains separate and globally unique by
Organization/DataSource/schema/table across all MetaTable scopes.

### Secrets And Constants

The two designed scopes are:

- `global`: available to authorized consumers throughout one Organization and
  stored without an environment foreign key; and
- `environment`: attached to exactly one same-Organization environment.

Existing Secret and Constant rows migrate to `global` with a null environment
foreign key. This preserves their Organization-wide availability and existing
public UIDs. They are not silently assigned to production or any other
environment.

The approved effective set for a Project Executor in environment `E` is:

```text
Organization-global resources
+ resources scoped to E
```

Do not confuse those platform configuration resources with workflow API
`2.0.0` `env_vars`. A workflow literal is target-owned process configuration
stored on one Job or one runtime target's backing Job. It does not perform
global-plus-environment name resolution, create a Secret or Constant, select
an Organization Environment, or change ProjectBranch assignment. The branch's
backend-derived environment remains the authorization and discovery boundary;
the literal only reaches the target process after its normal deployment path.

Resources from another environment are not eligible. When a global and an
environment row share the same logical `(namespace, name)` identity, the
approved name-based resolution selects the environment row. Public-UID lookup
remains exact and never substitutes a same-name row.

Before creating a Secret or Constant, use the canonical non-mutating creation
preflight:

```text
POST /api/v1/secrets/preflight-create/
POST /api/v1/constants/preflight-create/
```

It warns when an environment resource will override an existing global
resource or when a new global fallback will remain overridden by existing
environment resources. The warning reports resource identity, scopes,
affected environment, and the resulting winner without exposing Secret values.
Same-scope duplicates remain `409` conflicts. Creation rechecks and returns the
same warning metadata. No separate MCP preflight tool is approved or deployed.

Availability is not Secret injection. Secret value access keeps its stronger
authorization, and `ProjectSecret` remains the explicit branch assignment and
alias used by injection workflows.

### Project Coding Agents

Agent list, quick-search, and semantic-search require one
`organization_project_environment_uid`. Apply this boundary before filtering
or ranking and return only typed Project Coding Agents whose persisted
ProjectBranches belong to that environment. This permits discovery across
Projects only when the exact branches share the same Organization Environment.
Project Coding Agents from every other environment and unscoped Agent types are
excluded.

An authorized human or local caller first uses
`organization_environment.list`, presents the visible choices to the user,
and asks which environment should bound the work. The selected public UID is
then required on `agent.list` and `agent.search`. A deployed Project Executor
does not list or choose environments: Astro Tau injects the UID provided by
the backend runtime context and removes it from the model-visible MCP schema.
Never ask a deployed Project Executor user to select an environment, and never
infer or widen scope from Organization membership, repository branch text,
DataSource equality, or prompt input.

Same-environment discovery does not grant arbitrary session access. Delegation
to another Project Coding Agent requires a caller-owned parent session, and the
persisted parent-child relationship authorizes subsequent delegated runtime-
access and task operations. Project Executor subagent bindings require both
endpoints to be Project Coding Agents in the same environment, and the calling
runtime may manage only its own outbound bindings.

### DataSource

The environment DataSource selects where future platform-managed
MetaTable-oriented work is routed. It does not override the selected
Connection/DataSource of an external registration, define environment identity,
or prove that existing MetaTables or physical data belong to the environment.

Deleting a DataSource receives no new blocker merely because an environment
references it. Environment-wide MetaTable deletion protection protects tables,
not the DataSource record.

### Jobs, Releases, And Project Executors

Jobs, ResourceReleases, and Project Executor services remain owned by an exact
ProjectBranch. They do not move under the Organization Environment. The branch
links them to their environment context. Their project-code images must carry
verified source provenance for the same exact ProjectBranch and commit. At
runtime, backend authentication derives and issues the ProjectBranch context;
a deployed SDK does not inspect Git or use image provenance as runtime
ownership.

## Understand The Approved Management Surface

The canonical environment-management resource is approved as:

```text
OrganizationProjectEnvironmentViewSet(ModelViewSet)
/api/v1/organization-project-environments/
```

This establishes one Organization-level collection/detail resource rather than
an endpoint nested below each Project. Public lookup uses the environment UID.
The ADR defines list, create, retrieve, partial-update, and delete intent and
does not define full-replacement PUT.

The route is deployed with the accepted serializer fields, filters,
Organization-admin mutation permissions, and transition restrictions. Project
Executor credentials can observe only their derived environment and cannot
mutate this resource. The read-only `organization_environment.list` MCP tool
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
a Project, provider branch, DataSource, table, Secret, release, or deployment.

### 3. Project And Initial Branch Creation

Canonical Project creation creates the logical Project and initial exact
`main` ProjectBranch. The backend resolves that branch to the Organization's
production environment. The project-creation caller does
not submit an environment UID.

### 4. Signed Provider Branch Push

After the Organization administrator creates the environment that allows the
exact branch, a signed provider push idempotently creates the missing sibling
ProjectBranch under the same logical Project and then runs canonical repository
reconciliation. Missing environment configuration produces ignored reason
`organization_environment_not_configured`; it does not silently use production
and creates nothing.

The push does not copy environment resources, Secrets, Jobs, releases,
deployments, runtime history, or physical data. It never creates the
environment or selects its DataSource. Delivery replay and concurrent pushes
must converge on one `(project, repository_branch)` row.

The accepted lifecycle removes the manual repository `import-branch` action,
its serializer/schema/service, and `ProjectBranch.clone_with_new_branch`
without a compatibility path. Read-only provider branch discovery remains.
Until that cutover is deployed, report the gap instead of claiming that an
unknown pushed branch is already provisioned automatically.

### 5. Project Executor Deployment And Runtime

Project Coding Agent preparation remains repository work owned by the
`project-to-agent` skill. Deployment creates or reconciles the canonical
ProjectBranch-owned Project Executor target and service. Under the environment
design, authenticated Project Executor platform operations derive data and
configuration scope through the persisted service-to-branch-to-environment
chain.

Environment selection is not a deployment input and must not be stored again
on the service as a caller-editable field.

### 6. Code Promotion And Release Deployment

Environment lifecycle and release lifecycle are different:

```text
Git commit or exact-commit tag
  -> synchronize one exact ProjectBranch
  -> evaluate each target-owned automatic redeployment policy
  -> deploy the ProjectBranch-owned ResourceRelease or Project Coding Agent
  -> create or reuse canonical DeploymentRun history

ProjectBranch
  -> OrganizationProjectEnvironment
  -> data and configuration context
```

The environment itself is not deployed and owns no DeploymentRun.

To promote code toward another environment, the user's Git/CI workflow moves
the code to the exact provider branch required by the target environment. The
platform then synchronizes that target ProjectBranch and follows its normal
release policy. Do not promote code by rewriting
`ProjectBranch.organization_project_environment`.

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
- history, DataNode progress, or checkpoints;
- Secrets, Constants, or ProjectSecret assignments;
- Jobs, schedules, releases, or deployment provenance; or
- DataSource or Alembic ownership.

Configuration promotion means explicitly creating or selecting the intended
global or target-environment resources under the approved authorization model.
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

Project Alpha branch `research` and Project Beta branch `research` may share
the `research` environment. Project Beta branch `release/candidate` belongs to
`candidate-eu`, not `research`. A DataSource shared by both environments would
not merge their logical table or configuration identities.

If both the Organization and `research` define Constant
`runtime/LOOKBACK_DAYS`, accepted name resolution selects the `research` row
for its Project Executor. Retrieving the global Constant by its exact UID still
addresses the global row when that caller is eligible and authorized.

A release for Project Alpha branch `research` deploys that branch's persisted
current commit. It does not deploy the `research` environment and does not copy
research data into production.

## Route Work To The Correct Skill

- Use `project-design` to record why a Project uses particular exact branch
  lanes and which environment assumptions affect MetaTables, DataNodes, Jobs,
  APIs, CLI commands, project-agent behavior, and static sites.
- Use `project-to-agent` to prepare truthful repository instructions, skills,
  and the source card for a Project Coding Agent.
- Use `resource-release` to discover, configure, deploy, and observe a
  ProjectBranch-owned ResourceRelease.
- Use `organization_environment.list` before human/local Agent discovery to
  resolve visible environment names to public UIDs and obtain the user's
  explicit environment selection.
- Use `static-site` for the static-site specialization after the exact
  ProjectBranch is selected.
- Stop for a separately approved data-migration workflow when the requested
  action would move or reassign established environment state.

Do not add a new top-level Project Blueprint domain for environments. Record
environment assumptions in decisions, dependencies, constraints, and
acceptance criteria until a separately approved Blueprint contract says
otherwise.

## Stop Conditions

Stop and ask for direction when:

- the Organization, logical Project, exact ProjectBranch, and environment are
  being treated as one identity;
- a caller tries to select or PATCH the ProjectBranch environment directly;
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

1. the Organization and exact ProjectBranch identities involved;
2. the environment's role, required branch, and affected resource classes;
3. the caller context and whether environment scope is implicit or explicit;
4. whether the request changes code, deployment, configuration, data, or an
   environment mapping;
5. the applicable accepted ADR-031 rule and any separately required migration
   design; and
6. the next owning skill or canonical application workflow.
