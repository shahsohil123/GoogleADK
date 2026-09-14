"""Builds the ADK Runner backing the A2A service, wired to Vertex AI Agent
Engine's Session Service and Memory Bank instead of the in-memory defaults
`to_a2a()` would use — see ../create_session_storage.py and
../create_memory_bank.py.
"""

from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import InMemoryCredentialService
from google.adk.runners import Runner

from sights_researcher_agent.agent import root_agent
from sights_researcher_agent.vertex_services import build_memory_service, build_session_service


async def create_runner() -> Runner:
    return Runner(
        app_name=root_agent.name,
        agent=root_agent,
        artifact_service=InMemoryArtifactService(),
        session_service=build_session_service(),
        memory_service=build_memory_service(),
        credential_service=InMemoryCredentialService(),
    )
