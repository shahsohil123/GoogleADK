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

from sights_researcher_agent.agent import root_agent
from sights_researcher_agent.vertex_services import build_memory_service, build_session_service

# See trip_planning_agent/runner.py for why this is wrapped in an App with
# context caching — same rationale, same ADK-native mechanism.
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
