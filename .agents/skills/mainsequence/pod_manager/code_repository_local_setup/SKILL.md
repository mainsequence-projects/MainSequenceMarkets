---
name: code-repository-local-setup
description: Set up a newly created or existing initialized Main Sequence CodeRepository as a verified local checkout and establish local authentication through a backend-issued MCP-to-CLI handoff or an injected runtime credential. Use after CodeRepository creation, when preparing one locally, or when its local authentication must be refreshed.
---

# Main Sequence CodeRepository Local Setup

Use this skill after creating a Main Sequence CodeRepository or when a user asks
to set up an existing CodeRepository on the calling coding agent's machine.

The MCP server supplies authenticated platform state and repository-access
operations. The calling host owns the local filesystem, Git, SSH private keys,
credential store, and editor. The external agent selects and sequences the
workflow; the MCP server does not clone repositories or write local files.

## Completion Contract

Report local setup as complete only when all of the following are true:

- `code_repository.get` returns the CodeRepository and its lightweight
  `{uid, repository_branch}` branch selector;
- `code_repository_branch.get` confirms that the selected CodeRepositoryBranch has
  `is_initialized=true`;
- `github_repository_binding.get` confirms that the CodeRepository's GitHubRepositoryBinding has a
  nonempty clone URL;
- the user confirmed the fully resolved canonical checkout path;
- the selected local directory is either a verified checkout of that exact
  repository or a newly completed clone;
- repository access was verified using a caller-owned SSH private key;
- `.env` contains the Main Sequence endpoint and one complete supported
  authentication mode; it contains no repository or branch identity variable,
  because canonical local identity is resolved from the verified Git checkout;
- local CLI/runtime authentication was established through either the
  backend-issued MCP handoff or the existing injected runtime-credential lane,
  without returning credentials through MCP or model-visible output;
- `.env` is excluded from Git; and
- the repository's own `AGENTS.md` and relevant skills have been read before
  implementation begins.

A successful clone without working local authentication is partial setup, not
completed setup. Preserve the checkout and report the remaining authentication
step rather than deleting successfully cloned source.

## Preserve The Boundary

The skill owns the platform-aware sequence, readiness checks, safe repository
identity rules, credential-materialization contract, verification, and
handoff.

Git branch discovery in this skill applies only to a genuine caller-owned local
checkout. A deployed JobRun, CodeRepository Executor, or runtime ResourceRelease must
use the backend-issued `runtime_code_repository_context.code_repository_branch_uid`; it must not
inspect Git, infer a branch from its working directory, or persist a competing
CodeRepositoryBranch selector.

Do not:

- ask the MCP server to read or write a caller-local path;
- send an SSH private key, access token, refresh token, runtime credential
  secret, `.env` content, or local absolute path in an MCP tool argument;
- request or expose the MCP Authorization header through a tool;
- print, summarize, copy to chat, or commit credential values;
- infer initialization merely because `code_repository.create` returned;
- silently ignore deploy-key registration failures;
- overwrite an existing directory or repoint an existing Git remote;
- recursively scan a home directory to find a checkout;
- treat `.env` as repository-owned documentation; or
- require Python, the Main Sequence SDK, or the Main Sequence CLI merely to
  inspect CodeRepository readiness, register the deploy key, or clone. A runnable
  SDK checkout may then use its installed CLI for the approved authentication
  handoff and `.env` rendering.

## Resolve And Wait For The CodeRepository

1. Keep the CodeRepository UID returned by `code_repository.create`, or resolve an
   existing CodeRepository with `code_repository.list`, `code_repository.search`, and `code_repository.get`.
2. Read the CodeRepository with `code_repository.get`. Its `branches` collection is a
   selector only and contains exactly `uid` and `repository_branch`. Do not
   expect readiness, configuration, or repository fields on these items.
3. Select one exact branch. A newly created CodeRepository initially has its created
   `main` CodeRepositoryBranch; otherwise use the branch explicitly selected by the
   user or calling flow. Do not infer a default, entry, oldest, or current
   branch from collection order.
4. Read the selected branch with `code_repository_branch.get`. Keep its UID only for
   the remote setup operations that explicitly require a CodeRepositoryBranch.
5. Read the CodeRepository's `github_repository_binding_uid` with `github_repository_binding.get`.
   `git_ssh_url` and `git_repo_url` belong only to GitHubRepositoryBinding; never treat a
   clone URL as CodeRepositoryBranch state.
6. If `is_initialized` is false, wait and retry `code_repository_branch.get` with a
   bounded interval. If the GitHubRepositoryBinding clone URL is not ready, retry
   `github_repository_binding.get`. Do not retry `code_repository.create`.
7. If initialization does not complete within the user's available working
   window, report the CodeRepository UID, selected branch name and UID, and
   current readiness state. Do not invent a repository URL or continue with a
   partial provider result.

Repository initialization is platform state. Polling it is caller behavior;
it is not an MCP task or subscription.

## Select A Safe Local Destination

Treat the user-selected path as the organization-independent Main Sequence
development base. Default that base to:

```text
~/mainsequence
```

Resolve the authenticated user's Main Sequence organization name and normalize
it as a filesystem-safe organization slug: lowercase it, replace unsupported
characters with `-`, and trim leading or trailing `-`. Do not use a GitHub
organization in place of the user's Main Sequence organization.

Always append the organization slug and `code-repositories` directory to the selected
base, including when the user chooses a custom base. Resolve the final checkout
as:

```text
<base>/<organization-slug>/code-repositories/<safe-code-repository-name>-<code-repository-uid>
```

For example, the default base resolves to:

```text
~/mainsequence/<organization-slug>/code-repositories/<safe-code-repository-name>-<code-repository-uid>
```

If the user selects `/work/mainsequence`, resolve the checkout under
`/work/mainsequence/<organization-slug>/code-repositories/`; never place the code repository
directly under `/work/mainsequence` and never omit the organization segment.

Show the user the fully resolved final checkout path and ask for confirmation
before creating directories, generating a key, registering a deploy key, or
cloning. If the host cannot resolve the organization name from its authenticated
profile, ask the user to identify it before constructing or confirming the
path. Do not fall back to a `default` organization directory.

The directory shape is a local convention, not a platform identifier. Use the
CodeRepository UID for aggregate operations and deploy-key registration. Use
the selected CodeRepositoryBranch UID only for explicit branch reads and clone branch
selection. After checkout, local CLI workflows derive branch context from Git
and must not require users to manage or persist that UID.

Before creating anything:

1. Inspect only the confirmed organization code-repositories root, resolved target, and
   current workspace.
2. If a candidate checkout exists, read its `origin` URL and resolve its
   authenticated CodeRepository context without printing credential values.
3. Reuse it only when repository origin and CodeRepository identity agree.
4. Stop on an occupied nonrepository directory, a different origin, or a
   conflicting CodeRepository identity or repository branch. Do not delete, rename, or
   overwrite it automatically.

## Establish Repository Access

Generate or reuse a code-repository-specific SSH key locally. Prefer Ed25519 when the
host supports it. The private key never leaves the host.

Call:

```text
code_repository.add_deploy_key
```

with:

- `code_repository_uid`: the public CodeRepository UID;
- `key_title`: a stable human-readable local host or harness identity; and
- `public_key`: only the OpenSSH public key text.

The tool delegates to the CodeRepository DRF action and returns an empty
object on canonical success. It does not return repository credentials or
provider metadata. Treat any MCP/DRF error as an incomplete access step and
surface it before cloning. Even after success, verify access by cloning or by a
nonmutating Git connection check because the external Git provider remains the
source of truth for repository acceptance.

Clone the GitHubRepositoryBinding `git_ssh_url` using the selected private key through
the host's local Git facilities, then check out the selected
`repository_branch`. Do not read a clone URL from CodeRepositoryBranch and do not place
the private-key content in a generated command. If a failed clone created a new
incomplete target directory, remove only that exact new directory after
verifying it was created by the current attempt. Never remove a pre-existing
directory.

After cloning, verify that `origin` identifies the expected GitHubRepositoryBinding and
that `git branch --show-current` equals the selected branch. Do not repoint a
remote or silently select another branch merely to make a mismatch disappear.

## Materialize Local Authentication

Do not copy credentials out of the MCP host's OAuth store. The supported normal
user lane creates a separate tracked CLI session through a short-lived PKCE
handoff:

1. On the machine that owns the checkout, run:

   ```text
   mainsequence login --mcp
   ```

2. Keep the command running. It sends only PKCE state and challenge to
   `POST /auth/mcp/cli-handoff/start/`. The backend creates the grant and
   returns its exact callback URI; the CLI never invents or supplies a
   localhost redirect URI.
3. Read the JSON tool request printed by the command and call exactly
   `auth.cli_authorize` with its `handoff_uid`. Do not alter or reuse a handoff
   UID from another process.
4. The waiting CLI polls the backend-issued callback with its private PKCE
   verifier. After authorization, the callback returns the normal tracked JWT
   pair directly to the CLI, which stores it through its existing credential
   store. Neither token enters the MCP tool result or model output.
5. Materialize local authentication through the canonical local command:
   command:

   ```text
   mainsequence code-repository refresh-token --path <checkout>
   ```

For this normal tracked-session lane, the resulting `.env` manages exactly:

```text
MAINSEQUENCE_ACCESS_TOKEN
MAINSEQUENCE_REFRESH_TOKEN
MAINSEQUENCE_ENDPOINT
```

For a Main Sequence coding-agent runtime, do not use the handoff to convert its
access-only principal into a refresh-backed user session. Its deployment
already injects the existing runtime-credential environment. The user never
authors that auth mode, credential, CodeRepositoryBranch UID, repository branch, or
Organization Environment UID. Run ordinary
`mainsequence login`, then `mainsequence code-repository refresh-token --path
<checkout>`; the CLI uses its current noninteractive runtime exchange and
preserves these supported entries:

```text
MAINSEQUENCE_AUTH_MODE=runtime_credential
MAINSEQUENCE_RUNTIME_CREDENTIAL_ID
MAINSEQUENCE_RUNTIME_CREDENTIAL_SECRET
MAINSEQUENCE_ACCESS_TOKEN
MAINSEQUENCE_ENDPOINT
```

Do not combine session-refresh and runtime-credential modes. Do not use
`mainsequence login --mcp --export`, manual token arguments, an MCP tool that
returns credentials, or the inbound MCP bearer as a substitute for the
handoff. A manually configured access token without refresh or durable runtime
credentials may permit the current MCP session, but it cannot provide durable
local SDK authentication. Report that limitation instead of claiming
completion.

The `code-repository refresh-token` render must:

1. read the existing file without returning it to the model;
2. preserve every unrelated entry;
3. omit existing `MAINSEQUENCE_TOKEN` and any legacy repository/branch
   identity variables from the rendered result rather than running a separate
   cleanup operation;
4. rewrite only the supported Main Sequence authentication entries and
   endpoint for the selected mode; repository identity remains derived from
   the verified Git checkout plus authenticated backend resolution; and
5. verify presence by key name only, never by printing values.

Initial materialization and later authentication refresh use this same render
contract. Refresh uses the CLI's established tracked session or an already
backend-injected runtime-credential exchange, then rewrites the managed entries
in `.env`. It never turns user-authored environment variables into deployed
runtime context; authenticated backend response state is required.
Refresh is not an MCP tool and does not expose credential values to the model.

Before materialization, verify that `.env` is ignored by the repository. If it
is not ignored, stop before writing secrets and ask for approval to correct the
repository ignore policy.

If the local machine does not have the CodeRepository CLI/runtime needed to
execute the repository, preserve the verified checkout and report local runtime
authentication as pending. Do not work around that limitation by adding a
token-export tool or reading the MCP client's credential store.

## Verify And Hand Off

Verify without revealing sensitive values:

- CodeRepository identity and lightweight branch selection from `code_repository.get`;
- selected CodeRepositoryBranch UID and `is_initialized` from `code_repository_branch.get`;
- clone URL and repository identity from `github_repository_binding.get`;
- exact Git `origin` agreement;
- current Git branch agreement with the selected `repository_branch`;
- clean repository identity and expected checkout root;
- `.env` presence, Git exclusion, and required key names;
- a nonsecret authenticated platform check through the selected local
  authentication mode; and
- repository instructions and existing user changes.

Then route work according to intent:

- use `code-repository-design` for architecture and the CodeRepository Blueprint;
- use the relevant repository or SDK execution skills for accepted MetaTable,
  TimeIndexTableUpdater, job, API, CLI, code-repository-to-agent, or static-site components;
- use `code-repository-to-agent` only when the CodeRepository itself must become a coding
  agent; and
- use an installed SDK's `code-repository-maintenance` skill for SDK-version-specific
  `.venv`, SDK, managed-skill, and Git publication workflows when that SDK is
  present.

The interface-neutral local setup does not depend on that optional SDK lane.

## Report Partial Failures Precisely

Identify the last completed boundary and preserve safe completed work:

- initialization pending: no local changes required;
- deploy-key failure: local key may exist, repository not yet accessible;
- clone failure: remove only a new incomplete clone created by this attempt;
- credential materialization unavailable: preserve the verified checkout and
  report local runtime authentication as pending;
- `.env` validation failure: do not print the file or secret values; and
- repository-instruction failure: preserve setup and report the missing or
  invalid repository-owned contract.

Never rerun `code_repository.create` or the entire setup workflow blindly after a
partial failure.
