# ADR 0021: The API serves the Analyst's tools over MCP

Status: Accepted.

Implementation status: implemented on `development`; not deployed. Tests cover the tools
over a stand-in API, the local tools through the client against the API, and `/mcp` on
the hosted API with real signed assertions. A hosted turn has not run.

Owner: this repository.

Related decisions: [ADR 0019](0019-metatables-analyst-agent.md) (the Analyst),
[ADR 0020](0020-analyst-reads-as-its-requester.md) (it reads as the person each turn
serves) and [ADR 0017](../api/0017-hosted-request-identity.md) (hosted caller identity).
Platform: MCP for FastAPI releases (`mainsequence.server.fastapi.install_mcp`) and the
`mcp_applications` an Agent declares (ms-tau-sdk 2.0.7).

## Context

The Analyst's six read tools ran in the agent and called the API's REST routes through
the client. Since mainsequence 9.0.19 a FastAPI release can serve MCP tools inside its
request identity, and a hosted Agent can declare the applications whose MCP it uses: the
platform resolves the release in the Agent's Environment and sends each call with the
delegation of the person the turn serves. Tau connects these applications only in hosted
sessions.

## Decision

The hosted API serves the read tools at `/mcp`, and the hosted Analyst uses them.

| Part | Rule |
| --- | --- |
| Tools | `list_namespaces`, `list_tables`, `deep_search`, `describe_table`, `run_sql` and `preview_rows`, with their schemas, live once in `metatables.analysis` over the API's REST contracts. |
| Endpoint | The hosted API installs a stateless MCP server with JSON responses at `/mcp` through `install_mcp`, after the request identity. The workflow's `metatables` resource sets `mcp_enabled: true`. |
| Authorization | A tool's calls run through the API's own routes, in process, with the caller assertion of the `/mcp` request. The SDK verifies the same caller, or the person it works for, and each route authorizes exactly as over REST, including ADR 0020's read-only rule. |
| Analyst | The agent declares `mcp_applications: [{resource: metatables}]` and gets `metatables__list_tools` and `metatables__call_tool`. Its extension registers the tools only in a local `ms-tau` session, where they call the local API as the developer. |
| Key | The API's workflow key is `metatables`, because MCP keys become tool prefixes and must match `^[a-z][a-z0-9_]{0,39}$`. |
| Time limits | Each tool declares how long an Agent should wait in its MCP `_meta` under `mainsequence.ai/timeout-seconds/v1` (ms-tau-sdk 2.0.9): 120 s, the bound of one in-process API call, and 300 s for `deep_search`, which the release's 300 s request timeout bounds. An undeclared tool would get the Agent's default of 60 s. |

## Consequences

- Any Agent or MCP client in the Environment can use the tools, each with its own access
  or that of the person it works for; MCP adds no authority beyond REST.
- The agent holds no MetaTables code path of its own when hosted: the platform finds the
  API release and attaches the delegation.
- The model calls the tools through `metatables__call_tool`, after listing them.
- Without a person, a hosted Analyst call reads as the agent's workload User, which holds
  no grants (ADR 0020), so it finds nothing.
- Renaming the key from `metatables-api` deletes and recreates the API release on the
  next push of each branch: the release keeps its name, `metatables`, but gets a new UID
  and URL. Clients discover it again by name.
- The local API serves no MCP: it has no request identity.
