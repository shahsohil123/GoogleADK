"""One-time setup: creates or updates the shared Vertex AI Agent Engine
resource used by every agent in this repo — either the Session Service
(conversation history) or the Memory Bank (durable, cross-session facts).

Usage:
    uv run python create_agent_engine.py session   # -> SESSION_AGENT_ENGINE_ID
    uv run python create_agent_engine.py memory    # -> MEMORY_AGENT_ENGINE_ID

If an engine with the matching display_name already exists in Vertex AI Agent
Engine, it updates and reuses that existing engine instead of creating a duplicate.
"""

import os
import sys
import warnings

import vertexai

warnings.filterwarnings(
    "ignore", message="The vertexai.Client class is deprecated.*", category=FutureWarning
)
from dotenv import load_dotenv

load_dotenv(".env", override=True)
if os.path.exists(".env.dev"):
    load_dotenv(".env.dev", override=True)

KINDS = {
    "session": ("travel-concierge-shared-state", "SESSION_AGENT_ENGINE_ID"),
    "memory": ("travel-concierge-memory-bank", "MEMORY_AGENT_ENGINE_ID"),
}

kind = sys.argv[1] if len(sys.argv) > 1 else ""
if kind not in KINDS:
    sys.exit(f"Usage: python {sys.argv[0]} {{{'|'.join(KINDS)}}}")
display_name, env_var = KINDS[kind]

client = vertexai.Client(
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1"),
)

existing_name = None
for eng in client.agent_engines.list():
    if getattr(eng.api_resource, "display_name", "") == display_name:
        existing_name = getattr(eng.api_resource, "name", None)
        break

if existing_name:
    print(f"Found existing Agent Engine '{display_name}', updating in place: {existing_name}")
    agent_engine = client.agent_engines.update(
        name=existing_name, config={"display_name": display_name}
    )
else:
    agent_engine = client.agent_engines.create(config={"display_name": display_name})
    print("Created Agent Engine:", agent_engine.api_resource.name)

agent_engine_id = agent_engine.api_resource.name.rsplit("/", 1)[-1]
print("Add to .env.dev:")
print(f"{env_var}={agent_engine_id}")
