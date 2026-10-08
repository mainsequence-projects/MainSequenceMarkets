# ADR 0020: The MetaTables Analyst reads as its requester

Status: Accepted.

Implementation status: implemented on `development`; not deployed. It builds on platform
ADR-0051 (requester-bound access, implemented 2026-10-06), ms-tau-sdk 2.0.8.dev44 for the
Analyst and mainsequence 9.0.19, whose `User.get_requester()` the API reads. Tests cover
admission through real signed assertions; a hosted turn has not run.

> Amendment (2026-10-08): [ADR 0021](0021-api-serves-the-analyst-tools-over-mcp.md) moves
> the hosted tools into the API's MCP endpoint. The platform sends each MCP call with the
> person's delegation, so the Analyst holds no MetaTables code path of its own.

Owner: this repository. The Analyst's tools and the API's authorization change together.

Related decisions: [ADR 0019](0019-metatables-analyst-agent.md) (the Analyst; this
replaces its own Reader grants), [ADR 0017](../api/0017-hosted-request-identity.md)
(hosted caller identity), [ADR 0007](../api/0007-database-enforced-table-access.md) (each
User queries as their own database role) and
[ADR 0002](../api/0002-application-administration-and-table-ownership.md) (Reader and
Writer grants). Platform: ADR-0051, requester-bound access for workloads
([ms-tau-sdk#66](https://github.com/mainsequence-sdk/ms-tau-sdk/issues/66)).

## Context

ADR 0019 runs every Analyst tool under the Analyst's own identity, granted Reader on
chosen namespaces. Anyone who can use the Analyst reads what that identity can read, so a
person can read tables through the Analyst that they cannot read themselves. A manager
who can only read a table can also grant it to the Analyst and then share the Analyst,
which exposes the table to people its Writer never granted.

Platform ADR-0051 lets an application an Organization admin enables act for the person
whose request it serves, the requester, and nobody else. The platform finds the person in
its own records and signs them into each call; the Agent never handles a person's token.
Since ms-tau-sdk 2.0.7 a delegated call carries the person's ordinary permissions,
including administrative ones, and the application that receives it decides what it may do.

## Decision

The Analyst holds no MetaTables grants and reads only as its requester. MetaTables
answers each Analyst call with exactly that person's access.

| Part | Rule |
| --- | --- |
| Enablement | The Analyst's resource declares `acts_for_requester: true`, which takes effect only when the pusher is an Organization admin; otherwise the Agent fails before it deploys. An admin can also set it on the Agent's workload User. |
| Requester | `current_requester()` (ms-tau-sdk) names the person the turn serves, or nobody: an Agent caller, the platform's own calls and local mode have none. |
| Calls | The hosted Analyst calls the API's MCP tools (ADR 0021), declared as `mcp_applications`. The platform signs the API's caller assertion with the Analyst as caller and the person as `requester`. |
| Authorization | For a call that carries a requester, `User.get_requester()` (mainsequence SDK), the API authorizes against that person: their direct and Team grants. The claim also carries the person's admin flag; MetaTables ignores it on these calls, so an Organization admin reads through the Analyst only what they are granted. |
| SQL | `run-query` runs on the requester's own database role (ADR 0007), so the database enforces that person's grants and nothing parses SQL. |
| Reads only | A call that carries a requester may use safe methods and the `run-query` and `read` POST routes, which run in read-only transactions; anything else is refused with 403. |
| No requester | Without a requester a call is the Analyst's own, and its workload User holds no grants, so it finds nothing. When the platform ends the delegation (the turn ended, the access was removed, more than 24 hours passed), the call is refused, never retried as the Analyst. |
| Audit | The requester is the actor of every grant check and SQL statement. |

Local mode is unchanged: the local Analyst already runs as the developer.

## Consequences

- Nobody reads more through the Analyst than they can read directly, and sharing the
  Analyst shares no data. ADR 0019's per-Environment Reader grants for the Analyst, and
  the manager path to grant it, are no longer used.
- During a turn the Analyst's code reads with the requester's authority. ADR-0051 makes
  that an Organization admin's decision, and people who use the Analyst are told so.
- Agent callers get no answers, because they have no requester.
- Answers land only in the requester's chat history or Tasks, which only the requester
  and Organization admins can read (ADR-0051 section 6).
- The API changes once, for every requester-bound caller, not just the Analyst: a call
  that carries a requester is authorized against that person and read-only.
- On implementation, the Analyst paragraph of
  [Ownership and sharing](../../security/ownership-and-sharing.md#workload-users) and
  ADR 0019 change from "grant the Analyst Reader" to "the Analyst reads as you".

## Verification

Tests show that a person reads through the Analyst exactly what they read directly, on
every tool including `run-query`; that an Organization admin reads only their own grants
through it; that a write carrying a requester is refused; that a tool without a requester
or with an ended binding returns no data; and that an Agent caller gets no data.
