"""Builds the ADK Runner backing the A2A service, wired to Vertex AI Agent
Engine's Session Service and Memory Bank instead of the in-memory defaults
`to_a2a()` would use — see ../create_session_storage.py and
../create_memory_bank.py.
"""

from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import InMemoryCredentialService
from google.adk.runners import Runner

from trip_planning_agent.agent import root_agent
from trip_planning_agent.vertex_services import build_memory_service, build_session_service

# The system instruction + tool declarations here are large and identical on
# every call within a conversation; caching them avoids re-billing/re-latency
# for that fixed prefix on every turn. Caching only kicks in from the second
# turn of a session onward once Gemini's own per-model token minimum is met
# (2048 tokens for Gemini 2.5, 4096 for Gemini 3) — short sessions never cache.
_APP = App(
    name=root_agent.name,
    root_agent=root_agent,
    context_cache_config=ContextCacheConfig(),
)


async def create_runner() -> Runner:
    return Runner(
        app=_APP,
        artifact_service=InMemoryArtifactService(),
        session_service=build_session_service(),
        memory_service=build_memory_service(),
        credential_service=InMemoryCredentialService(),
    )
