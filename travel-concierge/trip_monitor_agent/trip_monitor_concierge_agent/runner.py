"""Builds and eagerly initializes the ADK Runner backing the A2A service (and local execution).

Automatically wires:
- `SharedInMemorySessionService` & `SharedInMemoryMemoryService` when `LOCAL_MODE=true`
  (or `SharedVertexAiSessionService` & `SharedVertexAiMemoryBankService` in cloud mode).
- `BigQueryAgentAnalyticsPlugin` for streaming agent telemetry to BigQuery and
  Looker Agent Analytics (`https://marketplace.looker.com/marketplace/detail/agent_analytics`).
"""

from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import InMemoryCredentialService
from google.adk.runners import Runner

from trip_monitor_concierge_agent.agent import app as _APP
from trip_monitor_concierge_agent.vertex_services import build_memory_service, build_session_service

_ARTIFACT_SERVICE = InMemoryArtifactService()
_CREDENTIAL_SERVICE = InMemoryCredentialService()

# Eagerly instantiate Runner at import time so no lazy initialization occurs on the first request
RUNNER: Runner = Runner(
    app=_APP,
    artifact_service=_ARTIFACT_SERVICE,
    session_service=build_session_service(),
    memory_service=build_memory_service(),
    credential_service=_CREDENTIAL_SERVICE,
    auto_create_session=True,
)


async def create_runner() -> Runner:
    current_session_service = build_session_service()
    current_memory_service = build_memory_service()
    if (
        RUNNER.session_service is not current_session_service
        or RUNNER.memory_service is not current_memory_service
    ):
        RUNNER.session_service = current_session_service
        RUNNER.memory_service = current_memory_service
    return RUNNER
