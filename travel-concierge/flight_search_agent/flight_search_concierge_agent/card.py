"""Builds the AgentCard advertised over A2A."""

import asyncio
import os

from a2a.types import AgentCapabilities
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder

from flight_search_concierge_agent.agent import root_agent

RPC_PATH = "/a2a"


def _rpc_url() -> str:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
    engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")

    if project and location and engine_id:
        resource = f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"
        return f"https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api{RPC_PATH}"
    if os.environ.get("DOCKER_NETWORK_MODE", "").lower() in ("1", "true", "yes"):
        host = root_agent.name
    else:
        host = "localhost"
    return f"http://{host}:{os.environ.get('PORT', '8010')}{RPC_PATH}"


RPC_URL = _rpc_url()

AGENT_CARD = asyncio.run(
    AgentCardBuilder(
        agent=root_agent,
        rpc_url=RPC_URL,
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
    ).build()
)
