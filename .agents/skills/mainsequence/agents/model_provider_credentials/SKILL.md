---
name: model-provider-credentials
description: Discover one Django-owned built-in-plus-Organization-custom model-provider result, explain which rows use User credentials, and guide a user through built-in provider sign-in, cancellation, status, and revocation without creating an agent runtime or receiving final credentials.
---

# Model Provider Credentials

Use the platform tools as the source of truth. Do not guess provider or model
identifiers and do not publish a fixed provider/model table.

Django Agents owns the catalog, durable sign-in attempts, provider callback
and exchange, credential activation, refresh, and non-secret projections. MCP
dispatches directly to those canonical operations. Catalog and sign-in tools
never require or return an Agent, `AgentSession`, Astro deployment, runtime URL,
or runtime-access credential.

## Discover providers and models

1. Call `model_provider.list` before recommending a provider or model. It has
   no input.
2. Distinguish built-in rows (`known=true`) from Organization custom rows
   (`known=false`) in that same result. Do not make or recommend a second
   provider-discovery call.
3. Present relevant returned provider fields: `display_name`, `auth_methods`,
   `known`, `enabled`, `credential_status`, `authenticated`,
   `sign_in_available`, and `default_model`.
4. Use only the concrete returned `models`. A model includes its identifier,
   display name, API protocol, supported input kinds, reasoning flag, thinking
   levels, context window, and maximum output tokens.
5. For built-ins, explain that `known` and `enabled` are catalog/product state
   while `authenticated` is User credential state. For an Organization custom
   row, `authenticated=true`, `credential_status=missing`, empty
   `auth_methods`, and `sign_in_available=false` mean no per-User sign-in is
   required; they are not custom-provider lifecycle state.
6. The general catalog does not claim that a specific runtime supports, can
   select, or can execute a model.
7. If the user did not name a provider, ask them to choose from the live
   result. Do not substitute another provider silently.

The `schema_version` identifies the shared response contract.
`catalog_digest` identifies only the immutable built-in catalog; it is not a
revision or digest for Organization custom rows. Neither is runtime
compatibility or execution proof.

## Read credential state

Call `model_provider_credential.status` with no input. Status is non-secret,
derives the owner from the authenticated User, and never hydrates the stored
credential.

## Sign in

1. Require the selected provider to be present and enabled in the latest
   `model_provider.list` response.
2. If `known=false`, explain that authentication is managed on the
   Organization custom provider. Do not call User credential status, sign-in,
   cancellation, or revoke tools for it. MCP does not expose custom-provider
   mutation or secret capture.
3. If it is already authenticated, explain that no sign-in is needed.
4. If `sign_in_available=false`, explain that interactive sign-in is not
   currently configured. Do not call start.
5. Call `model_provider_credential.sign_in_start` with only the exact returned
   `provider`.
6. Retain the returned attempt `uid` only for this workflow.
7. Follow `next_action`:
   - `open_url`: show the exact `authorization_url`, optional `user_code`, and
     instructions, then ask the user to complete provider authorization; or
   - `none`: inspect the attempt status before acting again.
8. Call `model_provider_credential.sign_in_get` with
   `attempt_id=<returned uid>` until the attempt is terminal. Django owns the
   browser callback and advances due device-code polling durably.
9. Treat `completed`, `failed`, and `cancelled` as terminal. Report
   `error_code` when present, without inventing provider details.
10. After completion, call `model_provider_credential.status` again and report
   only the non-secret result.

Repeated start requests for the same authenticated User and provider converge
on the active durable attempt. After an ambiguous result, inspect canonical
state before asking the user whether to start again.

There is no manual-continuation tool. Never ask the user to paste a callback
URL or authorization code into the conversation or an MCP tool.

## Secret boundary

Never ask the user to paste an API key, access token, refresh token, password,
client secret, PKCE verifier, device authorization secret, callback value, or
complete credential into the conversation or an MCP tool.

Django exchanges provider authorization and persists the final credential.
MCP and the calling agent never receive the final credential. Do not call or
simulate hydrate, flush, exchange, refresh, or a generic HTTP operation.

## Cancel or revoke

Use `model_provider_credential.sign_in_cancel` with only the exact
`attempt_id` the user wants to stop. Django derives its provider and requires
the attempt to belong to the authenticated User.

Before `model_provider_credential.revoke`, explain that revocation invalidates
the stored provider credential and obtain explicit confirmation. Call it with
only the exact returned `provider` and a concise `reason`. Reuse the canonical
result; do not delete credential records or invent a reconnect path.
