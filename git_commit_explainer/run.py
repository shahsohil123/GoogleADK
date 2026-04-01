"""
Interactive runner for Git Commit Explainer.
Usage:
  python run.py                          # analyzes current directory
  python run.py /path/to/repo            # analyzes a specific repo
  REPO_PATH=/path/to/repo python run.py  # via env var
"""

import asyncio
import os
import sys

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import create_agent


async def run(repo_path: str):
    agent = create_agent(repo_path)

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="git_commit_explainer",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="git_commit_explainer",
        user_id="user",
    )

    print(f"\n Git Commit Explainer")
    print(f" Repo: {repo_path}")
    print(f" Model: claude-3-5-sonnet-v2")
    print(f" Policy: read-only git commands\n")
    print("=" * 60)
    print("NOTE: You will be prompted to approve each git command.")
    print("Type 'yes' or 'no' when asked.\n")

    # Initial analysis prompt
    user_message = types.Content(
        role="user",
        parts=[types.Part(text="Analyze this repository and give me a full report.")],
    )

    async for event in runner.run_async(
        user_id="user",
        session_id=session.id,
        new_message=user_message,
    ):
        # Handle tool confirmation requests
        if event.actions and event.actions.requested_auth_configs:
            pass  # handled by ADK

        # Print model responses
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text, end="", flush=True)

    print("\n" + "=" * 60)


if __name__ == "__main__":
    repo_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REPO_PATH", ".")
    asyncio.run(run(repo_path))
