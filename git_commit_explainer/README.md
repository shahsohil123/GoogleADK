# Git Commit Explainer

> An ADK agent that reads your git history, explains changes in plain
> English, and flags risky commits — built on the undocumented
> `ExecuteBashTool` in **[Google ADK](https://adk.dev)** v2.0.0 alpha.

![framework](https://img.shields.io/badge/framework-Google%20ADK%20v2.0.0a2-4285F4) ![model](https://img.shields.io/badge/model-Gemini-34A853)

---

## What this demonstrates

- **Shell tools behind an approval gate.** Every `git` command the agent
  runs requires explicit human approval in the dev UI before it executes.
- **Policy-constrained tool use.** A `BashToolPolicy` restricts the agent
  to a fixed allowlist of read-only git subcommands — anything else is
  blocked before the confirmation step.
- **Experimental ADK surface.** Uses `ExecuteBashTool` from
  `google.adk.tools.bash_tool`, an experimental API in ADK v2.0.0a2 that
  isn't in the official docs yet.

---

## The scenario

> *"What's changed on this repo over the last week and is anything
> worth reviewing before the release?"*

1. You point the agent at a repo path.
2. It runs `git log` to pull the last 20 commits.
3. For anything that looks interesting, it inspects diffs with
   `git diff` / `git show`.
4. It groups changes by feature/fix, flags commits touching auth,
   payments, migrations, secrets, or env configs, and prints a
   recommendation for reviewers.

---

## Architecture

```
                 "Explain recent changes in /path/to/repo"
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │  git_commit_explainer         │
                 │  (google.adk.Agent)           │
                 │  model: gemini-*-flash        │
                 └──────────────┬───────────────┘
                                │   tools=[ ExecuteBashTool(policy=...) ]
                                ▼
                 ┌──────────────────────────────┐
                 │  BashToolPolicy               │
                 │  allowlist: git log, diff,    │
                 │  show, status, branch,        │
                 │  shortlog, stash list         │
                 └──────────────┬───────────────┘
                                │   (blocks anything else)
                                ▼
                 ┌──────────────────────────────┐
                 │  human approval (dev UI)      │
                 └──────────────┬───────────────┘
                                │
                                ▼
                     `git` process in REPO_PATH
```

Every shell command takes two layers of permission to run: the policy
allowlist (static) and the human's click in the dev UI (interactive).

---

## Prerequisites

- **Python 3.11+**
- A git repo you want to explain (any local path)
- A Gemini API key from [AI Studio](https://aistudio.google.com/apikey)

---

## Setup

```bash
cd git_commit_explainer

# Install ADK v2.0.0 alpha (not yet on PyPI stable)
pip install "git+https://github.com/google/adk-python.git@v2.0.0a2"

# Set your API key
export GOOGLE_API_KEY=<your-gemini-key>
```

---

## Running it

### Option 1 — ADK dev UI (recommended)

```bash
REPO_PATH=/path/to/your/repo make web
```

Open the URL the dev UI prints, pick `git_commit_explainer`, and ask
*"What has changed recently?"*. Approve each git command as it runs.

### Option 2 — One-shot CLI

```bash
make run
```

Prompts the agent against the repo set by `REPO_PATH` (defaults to `.`).

---

## Project structure

```
git_commit_explainer/
├── agent/
│   ├── __init__.py         # exposes root_agent for adk discovery
│   └── agent.py            # ExecuteBashTool + BashToolPolicy allowlist
├── run.py                  # CLI entry point — takes a repo path
├── Makefile                # run / web
└── README.md
```

---

## Example output

```
## Summary
- 18 commits over 6 days by 3 authors
- Primary focus: payment service refactor and auth token refresh logic

## Recent Changes
- a3f1c2d: Extracted PaymentProcessor into separate service class (refactor)
- b7e9012: Fixed null pointer in token refresh — was causing silent auth failures
- ...

## Risk Flags
c4d8a91 — touches `auth/token_manager.py` and `.env.production`
  This commit modifies token expiry logic AND updates production env
  config in the same change. Worth reviewing: are the new expiry
  values intentional?

## Recommendations
- Review c4d8a91 before release — mixed concerns in one commit
- 4 hotfix commits in 2 days suggests instability in the payment module
```

---

## Key patterns

### 1. Allowlisted bash tool

```python
from google.adk.tools.bash_tool import ExecuteBashTool, BashToolPolicy

policy = BashToolPolicy(
    allowed_commands=[
        "git log", "git diff", "git show", "git status",
        "git branch", "git shortlog", "git stash list",
    ],
)

bash_tool = ExecuteBashTool(policy=policy)
```

The policy rejects anything outside the allowlist — writes, network
calls, even `git pull` — before the human ever sees a confirmation.

---

## Next steps

- **Swap the static allowlist for a per-repo policy** that reads a
  `.gitexplainer.yml` in the target repo (some repos may want to allow
  `git blame`, others may not).
- **Add a diff summariser tool** so the agent can call a dedicated LLM
  summariser on a commit instead of re-reading the full diff inline.
- **Deploy to CI** as a release-preview gate: run the agent against
  `origin/main..HEAD` and post the risk flags to the PR as a comment.
- **Move approvals to Slack** via the same plain-text approval pattern
  used in `travel_concierge` — approvers approve from their phone.
