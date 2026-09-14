"""Builds the AgentCard sights_researcher advertises over A2A."""

import asyncio
import os

from a2a.types import AgentCapabilities
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder

from sights_researcher_agent.agent import root_agent

RPC_PATH = "/a2a"


def _rpc_url() -> str:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION")
    engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")

    if project and location and engine_id:
        resource = f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"
        return f"https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api{RPC_PATH}"
    return f"http://localhost:{os.environ.get('PORT', '8003')}{RPC_PATH}"


RPC_URL = _rpc_url()

AGENT_CARD = asyncio.run(
    AgentCardBuilder(
        agent=root_agent,
        rpc_url=RPC_URL,
        capabilities=AgentCapabilities(streaming=True),
    ).build()
)
