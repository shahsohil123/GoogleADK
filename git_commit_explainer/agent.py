"""
Git Commit Explainer — ADK Demo using ExecuteBashTool
Explains recent git history, summarizes what changed, and flags risky commits.

Requires: google-adk v2.0.0a2
  pip install "git+https://github.com/google/adk-python.git@v2.0.0a2"
"""

import os
import warnings
from pathlib import Path

# Suppress experimental warnings for cleaner output
os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
# Force direct Anthropic API (not Vertex AI)
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
warnings.filterwarnings("ignore", category=UserWarning)

from google.adk import Agent
from google.adk.tools.bash_tool import ExecuteBashTool, BashToolPolicy

# Read-only git policy — agent can inspect but never modify
GIT_READ_POLICY = BashToolPolicy(
    allowed_command_prefixes=(
        "git log",
        "git diff",
        "git show",
        "git status",
        "git branch",
        "git shortlog",
        "git stash list",
    )
)

SYSTEM_INSTRUCTION = """
You are a Git Commit Explainer. Your job is to analyze a git repository using bash commands and produce a clear report.

You have access to a bash tool to run git commands. Use it to:

1. Run: git log --oneline -20
2. Run: git log --stat -10
3. Run: git diff HEAD~5..HEAD --stat

Then write a report with:

## Summary
- Main focus of recent work
- Number of commits and authors
- Time period covered

## Recent Changes
- Explanation of what changed in the last 10 commits

## Risk Flags
- Any commits touching auth, config, migrations, or secrets
- Explain why they need careful review

## Recommendations
- What to review before next release
- Any patterns suggesting technical debt

Be direct and reference actual commit hashes and file names.
"""


def create_agent(repo_path: str) -> Agent:
    """Create a Git Commit Explainer agent scoped to a specific repo."""
    workspace = Path(repo_path).expanduser().resolve()
    # Default workspace to home dir if path doesn't exist or isn't a git repo
    if not workspace.exists() or not (workspace / ".git").exists():
        workspace = Path.home()

    return Agent(
        model="gemini-2.0-flash",
        name="git_commit_explainer",
        description="Analyzes git history and explains recent commits, flagging risky changes.",
        instruction=SYSTEM_INSTRUCTION,
        tools=[
            ExecuteBashTool(
                workspace=workspace,
                policy=GIT_READ_POLICY,
            )
        ],
    )


# Export root_agent for `adk web` / `adk run`
# Set REPO_PATH env var to point to your repo, defaults to home directory
root_agent = create_agent(os.environ.get("REPO_PATH", str(Path.home())))
