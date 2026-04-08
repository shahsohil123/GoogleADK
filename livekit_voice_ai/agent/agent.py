"""
Voice-controlled ADK agent with safe, read-only bash access to the resources folder.
"""

import asyncio
import os
import shlex
import warnings
from pathlib import Path

os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
warnings.filterwarnings("ignore", category=UserWarning)

from google.adk import Agent
from google.adk.tools.bash_tool import BashToolPolicy, _validate_command

SAFE_BASH_POLICY = BashToolPolicy(
    allowed_command_prefixes=("ls", "cat", "head", "tail", "wc", "file", "stat", "grep", "pwd", "echo"),
)

WORKSPACE_PATH = Path(__file__).parent.parent / "resources"
WORKSPACE_PATH.mkdir(parents=True, exist_ok=True)


async def run_bash(command: str) -> dict:
    """Run a read-only bash command in the resources folder and return its output."""
    error = _validate_command(command, SAFE_BASH_POLICY)
    if error:
        return {"error": error}

    if command.startswith("/") or "../" in command or command.startswith("~"):
        return {"error": "Blocked: cannot access paths outside resources folder"}

    process = await asyncio.create_subprocess_exec(
        *shlex.split(command),
        cwd=str(WORKSPACE_PATH),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    return {
        "stdout": stdout.decode() if stdout else "",
        "stderr": stderr.decode() if stderr else "",
    }


root_agent = Agent(
    model="groq/meta-llama/llama-4-scout-17b-16e-instruct",
    name="voice_assistant",
    description="Voice-controlled file assistant for the resources folder.",
    instruction="""\
You are a file assistant with access to the resources folder.
Always use run_bash to answer questions about files:
- List files: ls
- Read a file: cat <filename>
- Search in files: grep <text> <filename>

Never guess file contents — always run a command first.
Keep answers short and direct.
""",
    tools=[run_bash],
)
