"""Deploys the PayPal payments agent to Vertex AI Agent Engine.

Run from the `paypal_a2a_agent/` directory (after `make install`):
    python deploy_agent_engine.py                  # first deploy
    python deploy_agent_engine.py <resource_name>   # redeploy in place

Requires the runtime service account (`AGENT_ENGINE_SERVICE_ACCOUNT` below)
to already have `roles/secretmanager.secretAccessor` and
`roles/aiplatform.user` on `GOOGLE_CLOUD_PROJECT` — see README.md.
"""
import os
import sys

import vertexai
from dotenv import load_dotenv
from vertexai import agent_engines

from paypal_agent.agent_engine_app import PayPalAgentEngineApp

load_dotenv()

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.environ.get("AGENT_ENGINE_STAGING_BUCKET", f"gs://{PROJECT}-agent-engine-staging")
SERVICE_ACCOUNT = os.environ.get(
    "AGENT_ENGINE_SERVICE_ACCOUNT", f"paypal-agent-engine@{PROJECT}.iam.gserviceaccount.com"
)

REQUIREMENTS = [
    "langgraph",
    "langgraph-checkpoint",
    "langchain-core",
    "langchain-google-vertexai",
    "langchain-mcp-adapters",
    "google-cloud-secret-manager",
    "requests",
]

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=STAGING_BUCKET)

kwargs = dict(
    requirements=REQUIREMENTS,
    extra_packages=["paypal_agent"],
    display_name="paypal-payments-agent",
    description=(
        "PayPal Sandbox payments agent built with LangGraph, using PayPal's "
        "own hosted MCP tools for orders, captures, and refunds."
    ),
    service_account=SERVICE_ACCOUNT,
    # GOOGLE_CLOUD_PROJECT/GOOGLE_CLOUD_LOCATION are reserved — Agent Engine
    # injects its own project/location automatically at runtime.
    env_vars={
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "PAYPAL_BASE_URL": os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"),
        "PAYPAL_MCP_URL": os.environ.get("PAYPAL_MCP_URL", "https://mcp.sandbox.paypal.com/sse"),
    },
)

if len(sys.argv) > 1:
    remote_app = agent_engines.update(sys.argv[1], agent_engine=PayPalAgentEngineApp(), **kwargs)
else:
    remote_app = agent_engines.create(PayPalAgentEngineApp(), **kwargs)

print("Deployed:", remote_app.resource_name)
