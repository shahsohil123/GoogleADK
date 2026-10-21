"""Builds the ADK Runner backing the A2A service (and local execution).

Automatically wires:
- `InMemorySessionService` & `SharedInMemoryMemoryService` when `LOCAL_MODE=true`
  (or `VertexAiSessionService` & `SharedVertexAiMemoryBankService` in cloud mode).
- `BigQueryAgentAnalyticsPlugin` for streaming agent telemetry to BigQuery and
  Looker Agent Analytics (`https://marketplace.looker.com/marketplace/detail/agent_analytics`).
"""

from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import InMemoryCredentialService
from google.adk.runners import Runner

from itinerary_concierge_agent.agent import app as _APP
from itinerary_concierge_agent.vertex_services import build_memory_service, build_session_service


async def create_runner() -> Runner:
    return Runner(
        app=_APP,
        artifact_service=InMemoryArtifactService(),
        session_service=build_session_service(),
        memory_service=build_memory_service(),
        credential_service=InMemoryCredentialService(),
    )
