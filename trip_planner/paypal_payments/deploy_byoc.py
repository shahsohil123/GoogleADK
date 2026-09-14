"""Deploys the PayPal payments agent to Vertex AI Agent Engine as a
Bring-Your-Own-Container (BYOC) A2A service — the exact same
`paypal_agent/agent.py` Starlette app `make start` runs locally, running in
an arbitrary container instead of Agent Engine's fixed query/stream_query
interface. There's no LangGraph-specific Agent Engine template (unlike
`AdkApp` for ADK agents), so this is the only way to run this agent on
Agent Engine at all — and, for either framework, the only way to get a real
A2A endpoint out of Agent Engine (its pickle-based deployment mode can't
serve arbitrary HTTP routes).

Build and push the image first:
    gcloud builds submit --tag "$GOOGLE_CLOUD_LOCATION-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/trip-planner-agents/paypal-payments-a2a:v1" .

Then deploy (from this directory, after `make install`):
    python deploy_byoc.py                  # first deploy
    python deploy_byoc.py <resource_name>   # redeploy in place

Once deployed, the agent card is served at:
    https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api/.well-known/agent-card.json

Requires the runtime service account (`AGENT_ENGINE_SERVICE_ACCOUNT` below)
to already have `roles/secretmanager.secretAccessor` on
`GOOGLE_CLOUD_PROJECT` — see README.md.
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
IMAGE_URI = f"{LOCATION}-docker.pkg.dev/{PROJECT}/{REPO}/paypal-payments-a2a:{TAG}"
SERVICE_ACCOUNT = os.environ.get(
    "AGENT_ENGINE_SERVICE_ACCOUNT", f"paypal-agent-engine@{PROJECT}.iam.gserviceaccount.com"
)

vertexai.init(project=PROJECT, location=LOCATION)
client = vertexai.Client(project=PROJECT, location=LOCATION)

config = {
    "display_name": "paypal-payments-a2a",
    "description": (
        "PayPal Sandbox payments agent (LangGraph), deployed as a BYOC A2A "
        "service — creates orders, captures payments, and issues refunds."
    ),
    "container_spec": {"image_uri": IMAGE_URI},
    "agent_framework": "custom",
    "service_account": SERVICE_ACCOUNT,
    "env_vars": {
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "PAYPAL_BASE_URL": os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"),
        "PAYPAL_MCP_URL": os.environ.get("PAYPAL_MCP_URL", "https://mcp.sandbox.paypal.com/sse"),
    },
}

print(f"Creating/updating Agent Engine from {IMAGE_URI} ...")
if len(sys.argv) > 1:
    engine = client.agent_engines.update(name=sys.argv[1], config=config)
else:
    engine = client.agent_engines.create(config=config)

print("Deployed:", engine.api_resource.name)
