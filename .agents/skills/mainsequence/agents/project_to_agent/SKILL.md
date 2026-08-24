---
name: project-to-agent
description: Prepare or review an existing Main Sequence project as a truthful project-backed coding agent by defining its project instructions, project-owned skills, and repository source card. Use for project-to-agent conversion work, not for general project architecture or administration of an already deployed Agent.
---

# Main Sequence Project To Agent

Use this skill to add an agent-facing surface to an existing Main Sequence
project repository.

The MCP server delivers this platform workflow. The calling coding agent
inspects and edits the repository. MCP does not inspect local files, generate
the agent definition, or perform model reasoning.

For general project architecture, use the platform `project-design` skill
first. Use this skill only when the requested outcome includes turning the
project itself into a coding agent.

## Preserve The Boundary

A project-backed coding agent operates on the capabilities and instructions of
its project repository. Preparing that surface does not require creating an
`agents/` directory or an `agent.py` implementation.

Do not:

- invent capabilities that the repository does not implement or document;
- describe managed Main Sequence scaffold skills as project capabilities;
- create or modify a deployed platform `Agent` as part of repository
  preparation;
- put runtime endpoints, credentials, or deployment configuration in the
  repository source card; or
- claim deployment success from repository changes alone.

The deployed Project Coding Agent owns a server-side, ProjectBranch-scoped
automatic redeployment policy. Repository preparation does not implement or
evaluate that rule. If deployment intent is part of an accepted Blueprint,
preserve its nested `automatic_redeployment_policy.tag_regex` semantics for the
later canonical deployment handoff: omission requests the generated
branch-specific SemVer rule and explicit null selects every commit. Do not add
`trigger_mode`, derive tags from branch text locally, or put runtime policy in
`.agents/agent_card.json`.

At runtime, the typed `UserProjectExecutorAgentService` derives its
Organization Environment through its persisted ProjectBranch. That trusted
chain scopes canonical MetaTable and configuration operations; the repository
source card, branch text, request payload, human JWT, and other coding-agent
service types cannot select or widen it. Use the `organization-environments`
skill for the complete resource and promotion lifecycle.

The same derived environment scopes Project Coding Agent interaction. Agent
list/search exposes only Project Coding Agents whose ProjectBranches belong to
that environment, including compatible branches from other Projects. Astro Tau
injects the backend-provided environment into MCP discovery and hides the
selector from the model. Delegation remains provenance-bound: the parent
session's Agent must be the calling Project Executor, while the target session
and handle inherit the parent session's `created_by_user`. That inherited User
owns model-provider credentials across every A2A hop; each target runtime
hydrates independently and never receives credentials in the A2A payload.
The runtime credential's responsible User remains the acting principal, not a
session-owner or credential fallback. Subagent bindings cannot cross
environments or target an unscoped Agent.

The Project Executor image inherits the exact verified source provenance of
its digest-pinned ProjectBranch project image and adds the executor bundle and
recipe identity. It must not clone the repository or independently select a
branch. Runtime credential exchange supplies the same backend-derived public
ProjectBranch context used by other branch-owned Kubernetes workloads. The SDK
uses that authenticated context without inspecting Git; repository source-card
metadata and container environment values are descriptive inputs, not the
action-authorization root. The runtime credential authenticates its persisted
responsible User, whose normal DRF, role, service-identity, object, and
operation policy applies without a token-scope action allowlist. The target
chain remains authoritative only for the agent's object namespace,
ProjectBranch, Organization Environment, and resource composition.

A Project Coding Agent declaration does not need an image UID or a prebuilt
image, regardless of its `automatic_deployment` setting. The backend owns the
exact-commit project-image and Project Executor image builds, so
`project_image.create` is not a prerequisite. The server-side target policy
separately owns later automatic-redeployment eligibility.

Both image stages use the shared durable orchestration contract. The
ProjectExecutorRun attaches typed project-image and runtime-image dependencies;
active relations block deletion, while terminal history may retain typed
tombstones without retaining the image row. Each provider attempt is a complete `ProjectImageBuildRun`
prepared before submission. Reserved image build arguments are derived from
those relations at submission and are never persisted as image UIDs or URIs in
generic build-argument JSON. Multiple deployment entry points converge on the
same exact build identity. Celery is only a wake-up, ambiguous submission is
never blindly retried, and neither project instructions nor project-owned
skills may encode image UIDs, provider handles, transient tags, or a `latest`
runtime selector.

## Required Repository Artifacts

Prepare and verify these project-owned artifacts:

```text
AGENTS.md
.agents/
├── agent_card.json
└── skills/
    └── <project-skill>/
        └── SKILL.md
```

The managed `.agents/skills/mainsequence/` tree contains platform and
SDK guidance. Never list that managed tree as a capability of the project
agent. Only project-owned skills outside that tree belong in the source card.

## Workflow

1. Inspect the repository purpose, documentation, implemented behavior, and
   existing agent artifacts.
2. State the intended agent role and an observable definition of success.
3. Verify every capability that the agent will claim.
4. Create or update the exact `## Project-Specific Instructions` section in
   `AGENTS.md`.
5. Create or update focused project-owned skills under `.agents/skills/`.
6. Create or update `.agents/agent_card.json` from the verified repository
   state.
7. Validate the instructions, skill files, source card, and all referenced
   paths together.
8. When deployment is requested, use the `project-workflows` skill to add one
   `project_coding_agent` declaration under `.mainsequence/workflows/`, validate
   it through the backend, and inspect its deployment run after commit. No
   ProjectBranch or Project Executor image input is needed for this declaration.
   API `2.1.0` may include non-secret target-owned `env_vars`; retrieve the live
   template for their exact shape. Those literals configure only the service
   backing Job and cannot create platform Secrets/Constants or select branch,
   environment, harness, image, or runtime credentials.

When the user asks only for a plan, stop after presenting the plan.

## Project Instructions

The `## Project-Specific Instructions` section must explain:

- the project's purpose and operating boundary;
- the work the project agent may perform;
- the work it must refuse or escalate;
- the project-owned skills that route specialized work; and
- repository-specific validation and safety rules.

Keep these instructions specific to the project. Do not duplicate the managed
Main Sequence instructions surrounding that section.

## Project-Owned Skills

Each project skill must correspond to a real, verified project capability.
Give it a narrow trigger, explicit inputs and outputs, concrete validation, and
clear stop conditions.

Do not create a skill merely to make the agent appear more capable. If the
underlying behavior is missing, report the gap and implement it only when the
user authorizes that project work.

## Repository Source Card

`.agents/agent_card.json` is the committed source definition for the project
agent. It is not the complete runtime-discoverable A2A Agent Card.

The source card owns stable repository-authored information:

- a meaningful human-facing agent name;
- a truthful description;
- the project agent definition version; and
- the stable Main Sequence A2A response-kind profile; and
- project-owned skill descriptions and their repository paths.

Do not encode the ProjectBranch UID or branch name into the agent name. The
platform already owns the association between the deployed Agent and its
ProjectBranch.

Use this source shape:

```json
{
  "name": "Portfolio Risk Analyst",
  "description": "Reviews portfolio risk using the verified capabilities of this project.",
  "version": "1.0.0",
  "capabilities": {
    "extensions": [
      {
        "uri": "https://mainsequence.ai/a2a/extensions/response-kind/v1",
        "description": "Select whether message:send returns a completed message or an asynchronous task.",
        "required": false,
        "params": {
          "supportedResponseKinds": ["message", "task"],
          "defaultResponseKind": "message"
        }
      }
    ]
  },
  "skills": [
    {
      "id": "portfolio-risk-review",
      "name": "Portfolio Risk Review",
      "description": "Review portfolio exposures and report material risks.",
      "tags": ["portfolio", "risk"],
      "examples": [
        "Review the current portfolio and identify its largest risk concentrations."
      ],
      "path": ".agents/skills/portfolio-risk-review/SKILL.md"
    }
  ]
}
```

Source-card rules:

- Use a short, stable, kebab-case `id` for every skill.
- Make skill IDs unique within the card.
- Use non-empty, factual tags that aid capability discovery.
- Keep every `path` repository-relative and point it to an existing Markdown
  skill file.
- Do not reference `.agents/skills/mainsequence/`.
- Do not include secrets, tokens, internal runtime locations, or local absolute
  paths.
- Include only response kinds implemented by the selected runtime and backend.
- Use `message` as the default and do not infer `task` support.
- Do not add `supportedInterfaces`, runtime security declarations, push
  notifications, or other runtime capability flags.

## Runtime A2A Card

During deployment, the platform runtime materializes the complete standard A2A
Agent Card from the repository source definition and the deployed runtime.

The runtime:

- supplies each concrete interface URL, protocol binding, and protocol version;
- supplies the security schemes and requirements enforced by that runtime;
- declares only transport capabilities and media modes that the deployed
  runtime actually supports;
- intersects the source response-kind declaration with the runtime and backend
  implementation before advertising it;
- projects source skills into standard A2A skill entries; and
- keeps repository-only paths and runtime credentials out of the public card.

Never guess these runtime-owned fields while preparing the repository.

The deployment declaration must not contain `harness`. A coding-agent
deployment registers its resolved harness on the backend service and exposes it
as read-only runtime identity. Repository authors select neither Pi nor Tau.
The workflow is ProjectBranch-scoped and the backend fixes the agent type to
`project-executor`.

## Validation

Before claiming the repository is prepared:

- parse `.agents/agent_card.json` as a JSON object;
- require non-empty `name`, `description`, `version`, and `skills`;
- require non-empty `id`, `name`, `description`, and `tags` for every skill;
- verify every skill ID is unique;
- verify every referenced skill path exists inside the repository;
- verify the card does not reference the managed Main Sequence skill tree;
- compare every capability claim with actual project behavior and
  documentation;
- verify `AGENTS.md` routes work consistently with the source card; and
- report that deployment and runtime availability remain separate steps.

## Expected Result

Report:

1. the verified purpose and capabilities of the project agent;
2. the project-owned files created or changed;
3. the validation performed;
4. unsupported or unresolved capability claims; and
5. the separate `project_coding_agent` workflow deployment and its observed
   deployment-run state, when applicable.
