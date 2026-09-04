---
name: a2a-communication
description: Discover an Environment-authorized Main Sequence Agent and use the canonical MCP A2A sender, with exact active caller-session proof for deployed Agent runtimes and a fully documented direct-runtime fallback.
---

# A2A Communication

Use this skill when another Main Sequence Agent is a better target for a
bounded request or when a request explicitly arrives through an A2A channel.
The workflow is language-neutral and does not require Python or the Main
Sequence CLI.

Main Sequence MCP advertises the canonical message-only `a2a.send_message`
sender. It resolves platform objects and runtime access, calls the target
runtime, and returns the validated response without exposing transport
credentials to the model. A harness may project the canonical name into its
local tool namespace; Astro exposes it as `mainsequence__a2a_send_message`.

Streaming and durable Task execution remain direct-runtime concerns. The
explicit direct-runtime construction below remains the complete fallback for
trusted A2A-capable hosts that do not expose the MCP tool or another
constrained sender. That fallback follows the runtime contract documented by
`docs/agents/adr/adr-016-direct-runtime-a2a-communication.md`.

## Preferred constrained sender

After fresh discovery selects a target, call `a2a.send_message`, or its harness-projected name such
as `mainsequence__a2a_send_message`. Its input is a host-tool call, not the A2A wire envelope. A new
target conversation uses:

```json
{
  "agent_uid": "<selected-Agent.uid>",
  "handle_unique_id": "<stable-task-handle>",
  "message": "<bounded request>",
  "message_id": "<stable-message-id>"
}
```

An existing target conversation uses:

```json
{
  "agent_uid": "<selected-Agent.uid>",
  "agent_session_uid": "<existing-target-AgentSession.uid>",
  "message": "<bounded request>",
  "message_id": "<stable-message-id>"
}
```

`agent_uid` is required and is copied from the selected `Agent.uid`. Exactly one session selector
is present: `handle_unique_id` for a new conversation or `agent_session_uid` for a continuation.
The host tool owns session resolution and constructs the A2A transport envelope shown under
Request Construction.

For an Agent-originated call, trusted harness code privately injects the exact active caller
session's UID, lease holder, and lease token through MCP request metadata. Django validates that
proof against the authenticated coding-agent service and the current unexpired `runtime_run`
lease. Caller-session identity is not a model-visible tool argument. A human MCP caller needs no
Agent caller-session proof; Django creates or reuses a root target session for the authenticated
User.

## Canonical Flow

1. For a human or local caller, call `organization_environment.list`, present
   the visible choices, and ask which environment should bound the work. Skip
   this step only when the user already selected an environment or the deployed
   Astro Orchestrator or Code Repository Executor runtime uses its
   backend-derived target Environment.
2. Discover a bounded set of candidates with `agent.search`, passing the
   selected environment UID when it is model-visible.
3. Inspect the selected Agent with `agent.get` when more detail is needed.
4. Create or reuse its session with `agent.get_or_create_session`.
5. Resolve the session's current runtime endpoint and short-lived credential
   with `agent_session.resolve_runtime_access`.
6. Inspect `runtime_interaction.can_submit`. Send the message directly to that
   runtime only when it is `true`; otherwise stop and surface the backend-owned
   notice without attempting to infer or execute remediation.
7. Read the selected Agent's `a2a_profile`, choose an advertised response kind,
   and send the versioned response-kind extension header.
8. Consume the returned `message` directly or follow the returned `task` using
   its documented lifecycle operations.

For the canonical MCP sender or a constrained host sender, steps 4 through 8 are one tool operation
after candidate selection. The detailed steps remain the fallback implementation contract.

The `AgentSession.uid` is the durable conversation context. Runtime locations
and credentials are ephemeral and must be resolved again when they expire or
the runtime changes.

Treat the returned `rpc_url` as an opaque location. Do not construct it from a
service name, tenancy, environment, numeric identifier, or remembered
subdomain; the platform binds runtime access to the canonical coding-agent
service UID.

Treat each runtime-access result as one atomic bundle:
`{rpc_url, token, coding_agent_service_uid}`. Never combine a remembered URL,
token, or service UID with any field from another resolution. Cache/group
identities must include Organization Environment UID, Agent UID, and service
or session UID; an `Astro` display label or handle string is not an identity.
If the active Environment changes, resolve the Environment-owned Agent/session
and the entire runtime-access bundle again.

## Discovery

Agent discovery always has one Organization Environment boundary. Human/local
`agent.list` and `agent.search` calls require
`organization_environment_uid`; authenticated deployed coding-agent runtimes
omit it because Django derives the Environment from the exact service target.
Both paths return only Code Repository Coding Agents
whose persisted CodeRepositoryBranches belong to that environment. For a human or
local MCP caller, call `organization_environment.list`, present each visible
name, required branch, production role, and public UID, and ask the user which
environment should bound the work. Continue limit/offset pagination until
`next` is null before presenting the choices. Resolve a user-supplied name
through that tool; never guess the UID or default to production. In a deployed
Astro Orchestrator or Code Repository Executor runtime, Django derives the
Environment and the host removes the argument from the model-visible tool
schema; never call the
environment selector workflow, ask the user for it, infer it from a branch
name, or try to override it. If a runtime host supplies a redundant UID
assertion, it must equal Django's derived value. Schema hiding or host injection
is defense-in-depth and never replaces backend authorization.

Build a concise discovery query from:

- the capability needed;
- relevant domain and task boundaries;
- the expected response shape;
- any required operating constraints.

Use a bounded result limit. Prefer the highest-ranked suitable candidate, not
merely a familiar name. If the user asked only which agents are available,
report the candidates and stop without sending work.

Do not replace platform discovery with local prompt-file inspection.

Every `agent.search` and `agent.get` result includes an `a2a_profile` with:

- `response_kind_extension_uri`;
- `supported_response_kinds`; and
- `default_response_kind`.

Missing legacy profile data means Message-only support. Never infer Task support
from runtime routes, an empty answer, or prior knowledge of another Agent.

## Session Reuse

Use a stable `handle_unique_id` for repeated work in the same target
conversation. Use a fresh task-specific handle for a genuinely new
conversation. A retry of the same get-or-create request reuses the same handle.
After a session is returned, reuse its public UID for later turns.

Handle uniqueness is `(agent, owner_user, handle_unique_id)`. The same User may
therefore have the same handle string on two distinct Environment-owned Astro
Agents. Never collapse or reuse those handles across Agent or Environment
boundaries.

If the request originates from an existing caller session, the trusted host
supplies its exact active session as the parent provenance. The canonical MCP
sender carries this privately; a direct-runtime fallback supplies that verified
UID when creating the target session. An Astro
Orchestrator or Code Repository Executor runtime may target only a typed Code
Repository Executor Agent in its own Organization Environment, and the parent
session's Agent must be the calling service's Agent. Astro-to-Astro and
executor-to-Astro delegation are not authorized. The backend copies
`parent_session.created_by_user` into the child
session and its handle. Never provide or infer a replacement User. Parent
linkage proves the calling Agent, while the inherited owner preserves the User
whose request the chain is serving. Parent linkage is durable authorization
provenance for later delegated runtime-access and task operations; it does not
broaden the task or grant access outside that exact parent-child relationship.

For a continuation, the target session's immediate `parent_session_uid` must
still equal the exact active caller session. Service-level authorization or a
different concurrent session of the same calling Agent is not equivalent
provenance.

Each target runtime independently asks Django for the child session owner's
model-provider credential after exact runtime/session authorization. Never
read, serialize, forward, log, or place provider credentials in A2A message
parts, session metadata, handle metadata, or tool output. The runtime
credential's responsible User remains the acting principal and does not become
the session owner or a credential fallback.

## Runtime Access Is Sensitive

The successful runtime-access result contains ephemeral sensitive data.

- Never echo, persist, cache beyond necessity, log, trace, or place the runtime
  credential in metrics or error details.
- Never send it to a different runtime or agent.
- Do not treat runtime access as authorization for any platform operation.
- If access is expired or unavailable, resolve it through the platform again
  instead of guessing an endpoint or token.

Treat `runtime_interaction.can_submit` as the sole new-message admission
decision. `is_ready` is routing health and `image_drift` is diagnostic input;
neither may override the interaction decision. When submission is blocked,
use the returned notice and `retry_after_ms` to decide whether to resolve again.
The MCP catalog intentionally has no runtime-remediation tool, so an Agent must
not turn a returned UI action into an arbitrary deployment call. A human with
deployment access performs explicit disruptive remediation through Command
Center.

The canonical MCP sender keeps the credential private. In the direct-runtime
fallback, the credential is visible only to the trusted host that makes the
request; keep it out of model-authored prose and reusable artifacts.

## Request Construction

Send a bounded request with a clear deliverable. When a machine-parseable result
is required, request a strict JSON object and specify its keys or schema.
Standard A2A responses expose message parts; do not request or depend on hidden
reasoning, thinking traces, tool traces, runtime paths, or transport internals.

Attachments may be sent as standard A2A file parts when the host and runtime
support them. Preserve filename and media type, enforce the current transport
size limit before sending, and do not encode local filesystem paths as a
portable contract.

Assign a stable message identifier before sending. If the exact same message
and attachments must be retried after a timeout or disconnect, reuse that
identifier. Use a new identifier when any logical request content changes.
This preserves request identity; it does not make direct `message` execution
durably idempotent. A lost direct response is ambiguous and a resend may execute
another turn. Select `task` when durable recovery is required.

For a normal request, select `message`. For durable asynchronous work, select
`task` only when `supported_response_kinds` contains `task`. Send the explicit
selection to the A2A v1 message endpoint returned in the atomic runtime-access
bundle:

```http
POST {rpc_url}{runtime_paths.a2a}/message:send
Authorization: Bearer {token}
Content-Type: application/a2a+json
Accept: application/a2a+json
A2A-Extensions: https://mainsequence.ai/a2a/extensions/response-kind/v1
```

`runtime_paths.a2a` must be present for this standard flow. Treat it as an
opaque backend-owned path. Never substitute `runtime_paths.chat`, a removed
`/api/a2a/sessions/.../runtime/chat` path, or a guessed `/api/a2a/v1` value.

The complete direct-Message request envelope is:

```json
{
  "message": {
    "messageId": "<stable-message-id>",
    "contextId": "<target-AgentSession.uid>",
    "role": "ROLE_REQUESTER",
    "parts": [
      {"text": "<bounded request>"}
    ]
  },
  "configuration": {
    "responseKind": "message"
  }
}
```

Activate it with an HTTP header whose value is the exact discovered extension
URI:

```http
A2A-Extensions: https://mainsequence.ai/a2a/extensions/response-kind/v1
```

Do not send the removed `returnImmediately` Boolean. Do not send
`responseKind` on `message:stream`, because streaming already selects a
different result contract.

### Requester and responder direction

Model and serialize message direction directly as `requester` and `responder`. The Main Sequence
A2A wire values are:

- requester -> `ROLE_REQUESTER` on the wire;
- responder -> `ROLE_RESPONDER` on the wire.

These values are transport direction, not principal identity. An Agent calling another Agent is
the requester for that exchange and sends `ROLE_REQUESTER`; it remains authenticated and audited
as an Agent through
`caller_kind=agent`, the caller Agent and service UIDs, and the authorized
parent-session UID. A human request uses the same requester wire direction but
has `caller_kind=user`. Never infer, assert, or override caller identity from
`message.role` or message metadata.

Request messages serialize the direction as `ROLE_REQUESTER`; response messages serialize it as
`ROLE_RESPONDER`. Do not emit or require the removed v0.3 `kind` discriminator on Message, Part,
or Task objects.

## Response Handling

- For `message`, require a valid `message` result and consume only documented
  response parts. The result must have the responder direction (`ROLE_RESPONDER`),
  and its `contextId` must equal the target AgentSession UID.
  An empty successful answer is a runtime contract failure.
- For `task`, require a valid `task` result, preserve its ID and context ID, and
  use task get/wait/cancel operations until a terminal state when the caller
  needs completion.
- Treat a response whose kind differs from the requested kind as a protocol
  error; never reinterpret it silently.
- Validate strict JSON before using it as structured input.
- Preserve the target session UID for the next turn in the same conversation.
- Treat a timeout or disconnect as an ambiguous outcome. In direct `message`
  mode, do not automatically resend because the first turn may have executed.
  Do not create a new target session or blindly send a new logical message.
- Report target-agent failures without exposing credentials or internal
  transport details.

## Delegation Boundaries

An orchestrating agent may discover candidates without confirmation. For a
user-originated request, obtain user confirmation before sending real work to
another agent unless the user's request already clearly authorizes that
delegation.

A runtime-owned child or executor may make bounded A2A calls within the active
task scope. It must not use A2A to broaden the task, authorization boundary, or
code-repository context.

When responding to an incoming A2A request, answer agent-to-agent. Follow an
explicit output schema exactly; otherwise return concise machine-usable
content.
