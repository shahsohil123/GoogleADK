"""Builds the AgentCard trip_planning advertises over A2A."""

import asyncio
import os

from a2a.types import AgentCapabilities
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder

from trip_planning_agent.agent import root_agent

RPC_PATH = "/a2a"


def _rpc_url() -> str:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION")
    engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")

    if project and location and engine_id:
        resource = f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"
        return f"https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api{RPC_PATH}"
    return f"http://localhost:{os.environ.get('PORT', '8004')}{RPC_PATH}"


RPC_URL = _rpc_url()

AGENT_CARD = asyncio.run(
    AgentCardBuilder(
        agent=root_agent,
        rpc_url=RPC_URL,
        # Verified directly against the deployed Vertex AI Agent Engine REST
        # proxy: a raw SendStreamingMessage call held the connection open
        # for 40+ seconds, delivering real incremental SSE chunks
        # (submitted -> artifactUpdate -> statusUpdate:COMPLETED), so
        # streaming is genuinely supported by this transport. (An earlier
        # client misconfiguration — setting ClientConfig.polling=True, which
        # sets request.configuration.return_immediately, cutting the stream
        # short after one event — was the real cause of an earlier
        # stuck-at-"submitted" bug, not a transport limitation.)
        # push_notifications=True requires a real push_sender wired up
        # server-side (see a2a_app.py) — to_a2a() doesn't provide one.
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
    ).build()
)
