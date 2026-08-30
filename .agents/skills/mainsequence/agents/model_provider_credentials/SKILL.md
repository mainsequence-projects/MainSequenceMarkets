---
name: model-provider-credentials
description: Discover the live Main Sequence model-provider and model catalog, explain which providers have active, revoked, or missing credentials, and guide a user through the maintained provider sign-in, continuation, cancellation, status, and revocation workflows without receiving final credentials.
---

# Model Provider Credentials

Use the platform tools as the source of truth. Do not guess provider or model
identifiers and do not publish a fixed provider/model table.

## Discover providers and models

1. Call `model_provider.list` before recommending a provider or model.
2. Present the returned providers with:
   - `auth_kind`;
   - `credential_status` (`active`, `revoked`, or `missing`);
   - `authenticated` and `sign_in_available`;
   - known and usable model counts; and
   - the concrete returned models and their `usable` values.
3. Explain that a listed model is known by the maintained runtime. Offer it as
   an execution choice only when `usable=true`.
4. Use returned model features and reasoning-effort capabilities when the user
   asks which model/configuration to select.
5. If the user did not name a provider, ask them to choose only from the live
   result. Do not substitute another provider silently.

Keep the returned `agent_session_uid` for the current workflow. It identifies
the exact maintained runtime session; it is not a credential.

## Read credential state

Call `model_provider_credential.status` with the returned session UID when an
exact-session status check is needed. Status is non-secret and never hydrates
the stored credential.

## Sign in

1. Require the selected provider to be present in `model_provider.list`.
2. If it is already authenticated, explain that no sign-in is needed.
3. If `sign_in_available=false`, explain the current maintained-runtime state.
   Do not call start.
4. Call `model_provider_credential.sign_in_start` with the exact returned
   provider and session UID.
5. Retain the returned provider, session UID, and attempt ID only for this
   workflow.
6. Follow `next_action`:
   - `wait`: call `model_provider_credential.sign_in_get` after a reasonable
     interval;
   - `open_url`: show the exact `authorization_url` and instructions, then ask
     the user to authenticate with the provider;
   - `enter_callback_url`: ask only for the short-lived callback URL or code
     produced by that exact attempt;
   - `prompt_input`: ask the exact returned prompt; or
   - `none`: inspect the terminal/current status before acting again.
7. Submit an explicitly requested callback/prompt response once with
   `model_provider_credential.sign_in_continue`. Never quote it back.
8. Continue reading the same attempt until it is `completed`, `failed`,
   `cancelled`, or otherwise terminal.
9. Call `model_provider_credential.status` again and report the non-secret
   result.

When start reports an existing in-progress attempt, reuse that attempt. Never
retry start automatically after an ambiguous response.

## Secret boundary

Never ask the user to paste an API key, access token, refresh token, password,
client secret, PKCE verifier, or complete credential into the conversation or
an MCP tool.

`sign_in_continue.input` is allowed only when the exact active attempt requests
`prompt_input` or `enter_callback_url`. Do not write that value to logs,
CodeRepository files, shell history, environment variables, Blueprints, or
skills.

The maintained runtime exchanges provider authorization and persists the final
credential through the canonical backend. MCP and the calling agent never
receive the final credential. Do not call or simulate hydrate or flush.

## Cancel or revoke

Use `model_provider_credential.sign_in_cancel` only for the exact active
attempt the user wants to stop.

Before `model_provider_credential.revoke`, explain that revocation invalidates
the stored provider credential and obtain explicit confirmation. Reuse the
canonical result; do not delete credential records or invent a reconnect path.
