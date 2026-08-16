---
name: project-local-setup
description: Set up a newly created or existing initialized Main Sequence Project as a verified local checkout and establish its local authentication through a backend-issued MCP-to-CLI handoff or an injected runtime credential. Use after project creation, when preparing a Project locally, when an MCP-authenticated coding agent must authenticate the project CLI, or when local project authentication must be refreshed.
---

# Main Sequence Project Local Setup

Use this skill after creating a Main Sequence Project or when a user asks to
set up an existing Project on the machine where the calling coding agent works.

The MCP server supplies authenticated platform state and repository-access
operations. The calling host owns the local filesystem, Git, SSH private keys,
credential store, and editor. The external agent selects and sequences the
workflow; the MCP server does not clone repositories or write local files.

## Completion Contract

Report local setup as complete only when all of the following are true:

- `project.get` returns the logical Project and its lightweight
  `{uid, repository_branch}` branch selector;
- `project_branch.get` confirms that the selected ProjectBranch has
  `is_initialized=true`;
- `git_repository.get` confirms that the logical Project's GitRepository has a
  nonempty clone URL;
- the user confirmed the fully resolved canonical checkout path;
- the selected local directory is either a verified checkout of that exact
  repository or a newly completed clone;
- repository access was verified using a caller-owned SSH private key;
- `.env` contains the Main Sequence endpoint, the logical Project UID, and one
  complete supported authentication mode; it never persists a ProjectBranch
  UID because the checked-out Git branch is the local branch selector;
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
checkout. A deployed JobRun, Project Executor, or runtime ResourceRelease must
use the backend-issued `runtime_project_context.project_branch_uid`; it must not
inspect Git, infer a branch from its working directory, or persist a competing
ProjectBranch selector.

Do not:

- ask the MCP server to read or write a caller-local path;
- send an SSH private key, access token, refresh token, runtime credential
  secret, `.env` content, or local absolute path in an MCP tool argument;
- request or expose the MCP Authorization header through a tool;
- print, summarize, copy to chat, or commit credential values;
- infer initialization merely because `project.create` returned;
- silently ignore deploy-key registration failures;
- overwrite an existing directory or repoint an existing Git remote;
- recursively scan a home directory to find a checkout;
- treat `.env` as repository-owned documentation; or
- require Python, the Main Sequence SDK, or the Main Sequence CLI merely to
  inspect Project readiness, register the deploy key, or clone. A runnable
  SDK checkout may then use its installed CLI for the approved authentication
  handoff and `.env` rendering.

## Resolve And Wait For The Project

1. Keep the logical Project UID returned by `project.create`, or resolve an
   existing Project with `project.list`, `project.search`, and `project.get`.
2. Read the logical Project with `project.get`. Its `branches` collection is a
   selector only and contains exactly `uid` and `repository_branch`. Do not
   expect readiness, configuration, or repository fields on these items.
3. Select one exact branch. A newly created Project initially has its created
   `main` ProjectBranch; otherwise use the branch explicitly selected by the
   user or calling flow. Do not infer a default, entry, oldest, or current
   branch from collection order.
4. Read the selected branch with `project_branch.get`. Keep its UID only for
   the remote setup operations that explicitly require a ProjectBranch.
5. Read the Project's `git_repository_uid` with `git_repository.get`.
   `git_ssh_url` and `git_repo_url` belong only to GitRepository; never treat a
   clone URL as ProjectBranch state.
6. If `is_initialized` is false, wait and retry `project_branch.get` with a
   bounded interval. If the GitRepository clone URL is not ready, retry
   `git_repository.get`. Do not retry `project.create`.
7. If initialization does not complete within the user's available working
   window, report the logical Project UID, selected branch name and UID, and
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

Always append the organization slug and `projects` directory to the selected
base, including when the user chooses a custom base. Resolve the final checkout
as:

```text
<development-base>/<organization-slug>/projects/<safe-project-name>-<project-uid>
```

For example, the default base resolves to:

```text
~/mainsequence/<organization-slug>/projects/<safe-project-name>-<project-uid>
```

If the user selects `/work/mainsequence`, resolve the checkout under
`/work/mainsequence/<organization-slug>/projects/`; never place the project
directly under `/work/mainsequence` and never omit the organization segment.

Show the user the fully resolved final checkout path and ask for confirmation
before creating directories, generating a key, registering a deploy key, or
cloning. If the host cannot resolve the organization name from its authenticated
profile, ask the user to identify it before constructing or confirming the
path. Do not fall back to a `default` organization directory.

The directory shape is a local convention, not a platform identifier. Use the
logical Project UID for aggregate operations. During this remote setup flow,
use the selected ProjectBranch UID only for explicit branch reads and deploy-key
registration. After checkout, local CLI workflows derive branch context from
Git and must not require users to manage or persist that UID.

Before creating anything:

1. Inspect only the confirmed organization projects root, resolved target, and
   current workspace.
2. If a candidate checkout exists, read its `origin` URL and existing
   `MAIN_SEQUENCE_PROJECT_UID` marker without printing other `.env` values.
3. Reuse it only when repository origin and logical Project identity agree.
4. Stop on an occupied nonrepository directory, a different origin, or a
   conflicting Project identity or repository branch. Do not delete, rename, or
   overwrite it automatically.

## Establish Repository Access

Generate or reuse a project-specific SSH key locally. Prefer Ed25519 when the
host supports it. The private key never leaves the host.

Call:

```text
project_branch.add_deploy_key
```

with:

- `project_branch_uid`: the selected public ProjectBranch UID;
- `key_title`: a stable human-readable local host or harness identity; and
- `public_key`: only the OpenSSH public key text.

The tool delegates to the ProjectBranch DRF action and returns an empty
object on canonical success. It does not return repository credentials or
provider metadata. Treat any MCP/DRF error as an incomplete access step and
surface it before cloning. Even after success, verify access by cloning or by a
nonmutating Git connection check because the external Git provider remains the
source of truth for repository acceptance.

Clone the GitRepository `git_ssh_url` using the selected private key through
the host's local Git facilities, then check out the selected
`repository_branch`. Do not read a clone URL from ProjectBranch and do not place
the private-key content in a generated command. If a failed clone created a new
incomplete target directory, remove only that exact new directory after
verifying it was created by the current attempt. Never remove a pre-existing
directory.

After cloning, verify that `origin` identifies the expected GitRepository and
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
5. Materialize the selected Project environment through the existing local
   command:

   ```text
   mainsequence project refresh_token --path <checkout>
   ```

For this normal tracked-session lane, the resulting `.env` manages exactly:

```text
MAINSEQUENCE_ACCESS_TOKEN
MAINSEQUENCE_REFRESH_TOKEN
MAINSEQUENCE_ENDPOINT
MAIN_SEQUENCE_PROJECT_UID
```

For a Main Sequence coding-agent runtime, do not use the handoff to convert its
access-only principal into a refresh-backed user session. Its deployment
already injects the existing runtime-credential environment. The user never
authors that auth mode, credential, ProjectBranch UID, repository branch, or
Organization Environment UID. Run ordinary
`mainsequence login`, then `mainsequence project refresh_token --path
<checkout>`; the CLI uses its current noninteractive runtime exchange and
preserves these supported entries:

```text
MAINSEQUENCE_AUTH_MODE=runtime_credential
MAINSEQUENCE_RUNTIME_CREDENTIAL_ID
MAINSEQUENCE_RUNTIME_CREDENTIAL_SECRET
MAINSEQUENCE_ACCESS_TOKEN
MAINSEQUENCE_ENDPOINT
MAIN_SEQUENCE_PROJECT_UID
```

Do not combine session-refresh and runtime-credential modes. Do not use
`mainsequence login --mcp --export`, manual token arguments, an MCP tool that
returns credentials, or the inbound MCP bearer as a substitute for the
handoff. A manually configured access token without refresh or durable runtime
credentials may permit the current MCP session, but it cannot provide durable
local SDK authentication. Report that limitation instead of claiming
completion.

The existing `project refresh_token` render must:

1. read the existing file without returning it to the model;
2. preserve every unrelated entry;
3. omit existing `MAINSEQUENCE_TOKEN` and `MAIN_SEQUENCE_PROJECT_ID` lines
   from the rendered result rather than running a separate cleanup operation;
4. rewrite the supported Main Sequence authentication entries, endpoint,
   and logical Project UID for the selected mode; never add
   `MAIN_SEQUENCE_PROJECT_BRANCH_UID`; and
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

If the local machine does not have the project CLI/runtime needed to execute
the project, preserve the verified checkout and report local runtime
authentication as pending. Do not work around that limitation by adding a
token-export tool or reading the MCP client's credential store.

## Verify And Hand Off

Verify without revealing sensitive values:

- logical Project identity and lightweight branch selection from `project.get`;
- selected ProjectBranch UID and `is_initialized` from `project_branch.get`;
- clone URL and repository identity from `git_repository.get`;
- exact Git `origin` agreement;
- current Git branch agreement with the selected `repository_branch`;
- clean repository identity and expected checkout root;
- `.env` presence, Git exclusion, and required key names;
- a nonsecret authenticated platform check through the selected local
  authentication mode; and
- repository instructions and existing user changes.

Then route work according to intent:

- use `project-design` for architecture and the Project Blueprint;
- use the relevant project or SDK execution skills for accepted MetaTable,
  DataNode, job, API, CLI, project-to-agent, or static-site components;
- use `project-to-agent` only when the Project itself must become a coding
  agent; and
- use an installed SDK's `project-maintenance` skill for SDK-version-specific
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
  invalid project-owned contract.

Never rerun `project.create` or the entire setup workflow blindly after a
partial failure.
