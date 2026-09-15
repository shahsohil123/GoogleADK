"""One-time setup: creates a shared Vertex AI Agent Engine resource used by
every ADK agent in this repo — either the Session Service (conversation
history) or the Memory Bank (durable, cross-session facts).

Usage:
    python create_agent_engine.py session   # -> SESSION_AGENT_ENGINE_ID
    python create_agent_engine.py memory    # -> MEMORY_AGENT_ENGINE_ID

Run once per kind, then copy the printed ID into each agent's .env.
"""

import os
import sys

import warnings

import vertexai

# vertexai.Client is deprecated in favor of agentplatform.Client, but the
# replacement's runtimes.update() doesn't patch a resource in place — it
# silently deletes and recreates it under a new resource ID (confirmed by
# testing directly against the API), which is unacceptable for a redeploy
# script. Suppressing this specific warning rather than "fixing" it back
# into that unsafe path.
warnings.filterwarnings(
    "ignore", message="The vertexai.Client class is deprecated.*", category=FutureWarning
)
from dotenv import load_dotenv

load_dotenv(override=True)  # .env on disk always wins over a stale Make-exported value

KINDS = {
    "session": ("trip-planner-shared-state", "SESSION_AGENT_ENGINE_ID"),
    "memory": ("trip-planner-memory-bank", "MEMORY_AGENT_ENGINE_ID"),
}

kind = sys.argv[1] if len(sys.argv) > 1 else ""
if kind not in KINDS:
    sys.exit(f"Usage: python {sys.argv[0]} {{{'|'.join(KINDS)}}}")
display_name, env_var = KINDS[kind]

client = vertexai.Client(
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

agent_engine = client.agent_engines.create(config={"display_name": display_name})
agent_engine_id = agent_engine.api_resource.name.rsplit("/", 1)[-1]

print("Created Agent Engine:", agent_engine.api_resource.name)
print("Add to each agent's .env:")
print(f"{env_var}={agent_engine_id}")
