"""Deploys sights_researcher to Vertex AI Agent Engine as a Bring-Your-Own-
Container (BYOC) A2A service — an arbitrary container running the same
`a2a_app.py` Starlette app as `make start`, instead of the pickle-based
`AdkApp` deployment in `deploy_agent_engine.py` (which only exposes Agent
Engine's own query/stream_query interface, not A2A).

Build and push the image first:
    gcloud builds submit --tag "$LOCATION-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/trip-planner-agents/sights-researcher-a2a:v1" .

Then deploy (from this directory, after `make install`):
    python deploy_byoc.py                  # first deploy
    python deploy_byoc.py <resource_name>   # redeploy in place

Once deployed, the agent card is served at:
    https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api/a2a/.well-known/agent-card.json
"""

import os
import sys

import vertexai
from dotenv import load_dotenv

load_dotenv()

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
REPO = os.environ.get("BYOC_REPO", "trip-planner-agents")
TAG = os.environ.get("BYOC_IMAGE_TAG", "v1")
IMAGE_URI = f"{LOCATION}-docker.pkg.dev/{PROJECT}/{REPO}/sights-researcher-a2a:{TAG}"

vertexai.init(project=PROJECT, location=LOCATION)
client = vertexai.Client(project=PROJECT, location=LOCATION)

config = {
    "display_name": "sights-researcher-a2a",
    "description": (
        "Sights Researcher, deployed as a BYOC A2A service — researches "
        "places to see at a destination, personalised via Memory Bank."
    ),
    "container_spec": {"image_uri": IMAGE_URI},
    "agent_framework": "custom",
    "env_vars": {
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "SESSION_AGENT_ENGINE_ID": os.environ["SESSION_AGENT_ENGINE_ID"],
        "MEMORY_AGENT_ENGINE_ID": os.environ["MEMORY_AGENT_ENGINE_ID"],
    },
}

print(f"Creating/updating Agent Engine from {IMAGE_URI} ...")
if len(sys.argv) > 1:
    engine = client.agent_engines.update(name=sys.argv[1], config=config)
else:
    engine = client.agent_engines.create(config=config)

print("Deployed:", engine.api_resource.name)
