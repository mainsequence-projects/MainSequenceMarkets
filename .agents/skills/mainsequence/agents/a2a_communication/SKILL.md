---
name: a2a-communication
description: Discover a target Main Sequence Agent, establish a stable AgentSession, resolve ephemeral runtime access, and communicate directly with the runtime using standard A2A semantics.
---

# A2A Communication

Use this skill when another Main Sequence Agent is a better target for a
bounded request or when a request explicitly arrives through an A2A channel.
The workflow is language-neutral and does not require Python or the Main
Sequence CLI.

Main Sequence MCP resolves platform objects and runtime access. It does not
proxy, stream, poll, cancel, or detach the live A2A turn. After resolving
access, the calling host communicates directly with the target runtime under
the standard A2A protocol and the runtime contract documented by
`docs/agents/adr/adr-016-direct-runtime-a2a-communication.md`.

## Canonical Flow

1. Discover a bounded set of candidates with `agent.search`.
2. Inspect the selected Agent with `agent.get` when more detail is needed.
3. Create or reuse its session with `agent.get_or_create_session`.
4. Resolve the session's current runtime endpoint and short-lived credential
   with `agent_session.resolve_runtime_access`.
5. Send the message directly to that runtime using the returned access data.
6. Consume standard response message parts.

The `AgentSession.uid` is the durable conversation context. Runtime locations
and credentials are ephemeral and must be resolved again when they expire or
the runtime changes.

## Discovery

Build a concise discovery query from:

- the capability needed;
- relevant domain and task boundaries;
- the expected response shape;
- any required operating constraints.

Use a bounded result limit. Prefer the highest-ranked suitable candidate, not
merely a familiar name. If the user asked only which agents are available,
report the candidates and stop without sending work.

Do not replace platform discovery with local prompt-file inspection.

## Session Reuse

Use a stable `handle_unique_id` for repeated work in the same target
conversation. Use a fresh task-specific handle for a genuinely new
conversation. A retry of the same get-or-create request reuses the same handle.
After a session is returned, reuse its public UID for later turns.

If the request originates from an existing caller session, supply that
authorized parent session UID when creating the target session. Parent linkage
records provenance; it does not broaden the task or grant access.

## Runtime Access Is Sensitive

The successful runtime-access result contains ephemeral sensitive data.

- Never echo, persist, cache beyond necessity, log, trace, or place the runtime
  credential in metrics or error details.
- Never send it to a different runtime or agent.
- Do not treat runtime access as authorization for any platform operation.
- If access is expired, unavailable, or reports runtime drift, resolve it
  through the platform again instead of guessing an endpoint or token.

The credential may be visible to the calling host because that host must make
the direct runtime request. Keep it out of model-authored prose and reusable
artifacts.

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

## Response Handling

- Consume only documented A2A response parts and status information.
- Validate strict JSON before using it as structured input.
- Preserve the target session UID for the next turn in the same conversation.
- Treat a timeout or disconnect as an ambiguous outcome; do not create a new
  target session or blindly send a new logical message.
- Report target-agent failures without exposing credentials or internal
  transport details.

## Role Boundaries

An orchestrating agent may discover candidates without confirmation. For a
user-originated request, obtain user confirmation before sending real work to
another agent unless the user's request already clearly authorizes that
delegation.

A runtime-owned child or executor may make bounded A2A calls within the active
task scope. It must not use A2A to broaden the task, authorization boundary, or
project context.

When responding to an incoming A2A request, answer agent-to-agent. Follow an
explicit output schema exactly; otherwise return concise machine-usable
content.
