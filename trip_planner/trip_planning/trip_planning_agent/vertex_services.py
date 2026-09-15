"""Builders for the two shared Vertex AI Agent Engine resources this agent
persists state to — Session Service and Memory Bank — created once via
../create_session_storage.py and ../create_memory_bank.py. The Memory Bank
is the same one sights_researcher writes traveler preferences to, so this
agent can also draw on (and add to) that shared memory directly.
"""

import os

from google.adk.memory import VertexAiMemoryBankService
from google.adk.sessions import VertexAiSessionService


def _location() -> str:
    return os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


def build_session_service() -> VertexAiSessionService:
    return VertexAiSessionService(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=_location(),
        agent_engine_id=os.environ["SESSION_AGENT_ENGINE_ID"],
    )


def build_memory_service() -> VertexAiMemoryBankService:
    return VertexAiMemoryBankService(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=_location(),
        agent_engine_id=os.environ["MEMORY_AGENT_ENGINE_ID"],
    )
