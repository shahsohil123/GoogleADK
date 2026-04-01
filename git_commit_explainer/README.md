# Git Commit Explainer

An ADK agent that analyzes your git history in plain English and flags risky commits.

Built using `ExecuteBashTool` — an undocumented tool in Google ADK v2.0.0 alpha.

## What it does

- Reads the last 20 commits with `git log`
- Inspects file-level changes with `git diff` and `git show`
- Explains what changed in plain English, grouped by feature/fix
- Flags commits touching sensitive areas: auth, payments, migrations, secrets, env configs
- Gives recommendations on what to review before the next release

## Setup

**Requirements:** Python 3.11+

```bash
# 1. Install ADK v2.0.0 alpha
pip install "git+https://github.com/google/adk-python.git@v2.0.0a2"

# 2. Set your API key
export GOOGLE_API_KEY=your_gemini_api_key

# 3. Run against any git repo
python run.py /path/to/your/repo

# Or use the ADK web UI
REPO_PATH=/path/to/repo adk web .
```

## Safety model

Every command requires your explicit approval before it runs. The agent is restricted to read-only git commands:

- `git log`
- `git diff`
- `git show`
- `git status`
- `git branch`
- `git shortlog`
- `git stash list`

Any other command (writes, network calls, etc.) is blocked by `BashToolPolicy` before it even reaches the confirmation step.

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
🚨 c4d8a91 — touches `auth/token_manager.py` and `.env.production`
   This commit modifies token expiry logic AND updates production env config
   in the same change. Worth reviewing: are the new expiry values intentional?

## Recommendations
- Review c4d8a91 before release — mixed concerns in one commit
- 4 hotfix commits in 2 days suggests instability in the payment module
```

## How it works

Uses `ExecuteBashTool` from `google.adk.tools.bash_tool` — an experimental,
undocumented tool in ADK v2.0.0a2. See the [source](https://github.com/google/adk-python/blob/v2.0.0a2/src/google/adk/tools/bash_tool.py).
