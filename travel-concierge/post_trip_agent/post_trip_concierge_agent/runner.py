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

from post_trip_concierge_agent.agent import app as _APP
from post_trip_concierge_agent.vertex_services import build_memory_service, build_session_service

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

# Pre-warm ADK lazy caches (_id_pairing_model_types, Gemini.api_client, FunctionTool declarations)
# at container startup so the first user request does not pay 15-30s of lazy import/schema overhead.
try:
    from google.adk.flows.llm_flows.contents import _id_pairing_model_types

    _id_pairing_model_types()
    for _tool in getattr(_APP.root_agent, "tools", None) or []:
        if hasattr(_tool, "_get_declaration"):
            _tool._get_declaration()
except Exception:
    pass


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
