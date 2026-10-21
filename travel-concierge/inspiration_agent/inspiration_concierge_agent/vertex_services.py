"""Builders for Session Service, Memory Bank, OpenTelemetry Cloud Trace Exporter,
and BigQuery Agent Analytics Plugin.

Supports two execution modes automatically:
1. **Cloud / Vertex AI Mode** (when `LOCAL_MODE` is false and `SESSION_AGENT_ENGINE_ID`
   + `MEMORY_AGENT_ENGINE_ID` are configured):
   - Uses `VertexAiSessionService` (`SESSION_AGENT_ENGINE_ID`)
   - Uses `SharedVertexAiMemoryBankService` (`MEMORY_AGENT_ENGINE_ID`) pinned to
     `app_name="travel_concierge"` across all 16 agents.
2. **Local / Docker Mode** (when `LOCAL_MODE=true` or `SESSION_AGENT_ENGINE_ID` /
   `MEMORY_AGENT_ENGINE_ID` are unset):
   - Spins up a shared `InMemorySessionService`
   - Spins up a shared `SharedInMemoryMemoryService` (`InMemoryMemoryService`
     pinned to `app_name="travel_concierge"`).

Also configures:
- **Google Cloud Trace OpenTelemetry Exporter** (`setup_cloud_trace_telemetry`)
  so all spans from `adk eval`, `adk web`, local Docker, and Agent Engine are
  exported to Cloud Trace (`https://telemetry.googleapis.com/v1/traces`).
- **BigQuery Agent Analytics Plugin** (`BigQueryAgentAnalyticsPlugin`) to stream
  agent telemetry into BigQuery (`<PROJECT_ID>.agent_analytics.agent_events`)
  with `create_views=True` for the Looker Marketplace Agent Analytics Block:
  https://marketplace.looker.com/marketplace/detail/agent_analytics
"""

import atexit
import logging
import os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True), override=False)

import socket as _socket

_orig_getaddrinfo = _socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    res = _orig_getaddrinfo(host, port, family, type, proto, flags)
    ipv4 = [r for r in res if r[0] == _socket.AF_INET]
    return ipv4 if ipv4 else res


_socket.getaddrinfo = _ipv4_getaddrinfo

try:
    import time as _time
    from copy import deepcopy as _deepcopy
    from google.genai._api_client import BaseApiClient

    BaseApiClient._use_aiohttp = lambda self: False
    if not getattr(BaseApiClient, "_fast_fallback_patched", False):
        _orig_async_req_once = BaseApiClient._async_request_once
        _orig_sync_req_once = BaseApiClient._request_once
        _fallback_until = 0.0

        def _make_fallback_req(http_request):
            req = _deepcopy(http_request)
            req.url = (req.url or "").replace("gemini-3-flash-preview", "gemini-2.5-flash")
            if isinstance(req.data, dict):
                gen_cfg = req.data.get("generationConfig")
                if isinstance(gen_cfg, dict):
                    gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
            req.timeout = 35.0
            return req

        async def _fast_async_request_once(self, http_request, stream=False):
            global _fallback_until
            url = http_request.url or ""
            is_gen = ":generateContent" in url or ":streamGenerateContent" in url
            if is_gen and "/locations/us-central1/publishers/google/models/gemini-3" in url:
                url = url.replace("us-central1-aiplatform.googleapis.com", "aiplatform.googleapis.com").replace("/locations/us-central1/publishers/google/models/", "/locations/global/publishers/google/models/")
                http_request.url = url
            if is_gen and "gemini-3-flash-preview" in url:
                if _time.monotonic() < _fallback_until:
                    return await _orig_async_req_once(self, _make_fallback_req(http_request), stream=stream)
                primary = _deepcopy(http_request)
                primary.timeout = 25.0
                try:
                    return await _orig_async_req_once(self, primary, stream=stream)
                except Exception:
                    _fallback_until = _time.monotonic() + 30.0
                    return await _orig_async_req_once(self, _make_fallback_req(http_request), stream=stream)
            return await _orig_async_req_once(self, http_request, stream=stream)

        def _fast_sync_request_once(self, http_request, stream=False):
            global _fallback_until
            url = http_request.url or ""
            is_gen = ":generateContent" in url or ":streamGenerateContent" in url
            if is_gen and "/locations/us-central1/publishers/google/models/gemini-3" in url:
                url = url.replace("us-central1-aiplatform.googleapis.com", "aiplatform.googleapis.com").replace("/locations/us-central1/publishers/google/models/", "/locations/global/publishers/google/models/")
                http_request.url = url
            if is_gen and "gemini-3-flash-preview" in url:
                if _time.monotonic() < _fallback_until:
                    return _orig_sync_req_once(self, _make_fallback_req(http_request), stream=stream)
                primary = _deepcopy(http_request)
                primary.timeout = 25.0
                try:
                    return _orig_sync_req_once(self, primary, stream=stream)
                except Exception:
                    _fallback_until = _time.monotonic() + 30.0
                    return _orig_sync_req_once(self, _make_fallback_req(http_request), stream=stream)
            return _orig_sync_req_once(self, http_request, stream=stream)

        BaseApiClient._async_request_once = _fast_async_request_once
        BaseApiClient._request_once = _fast_sync_request_once
        BaseApiClient._fast_fallback_patched = True
except Exception:
    pass

from google.adk.memory import InMemoryMemoryService, VertexAiMemoryBankService
from google.adk.sessions import InMemorySessionService, VertexAiSessionService

logger = logging.getLogger(__name__)

SHARED_MEMORY_APP_NAME = "travel_concierge"
_OTEL_INITIALIZED = False


def is_local_mode() -> bool:
    """Returns True when running locally/Docker with in-memory session & memory bank."""
    if os.environ.get("LOCAL_MODE", "").strip().lower() in ("1", "true", "yes"):
        return True
    if not os.environ.get("SESSION_AGENT_ENGINE_ID") or not os.environ.get("MEMORY_AGENT_ENGINE_ID"):
        return True
    return False


def setup_cloud_trace_telemetry(service_name: str = "travel-concierge") -> bool:
    """Configures OpenTelemetry to export all ADK, GenAI SDK, and HTTPX A2A
    traces to Google Cloud Trace (`telemetry.googleapis.com/v1/traces`),
    including during `adk eval` runs.

    Controlled via `OTEL_TO_CLOUD` (default `"true"`). Registers an `atexit`
    hook to `force_flush()` the `TracerProvider` so short-lived CLI processes
    such as `adk eval` flush all spans before exiting.
    """
    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return True

    if is_local_mode() and os.environ.get("OTEL_ENABLE_IN_LOCAL", "false").strip().lower() not in ("1", "true", "yes"):
        # Stateless local mode: configure local TracerProvider only (zero GCP Cloud Trace connections)
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            if not isinstance(trace.get_tracer_provider(), TracerProvider):
                trace.set_tracer_provider(TracerProvider())
            _OTEL_INITIALIZED = True
        except Exception:
            pass
        return False

    enabled_str = os.environ.get("OTEL_TO_CLOUD", "true").strip().lower()
    if enabled_str in ("0", "false", "no", "off"):
        return False

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project_id or project_id == "your-gcp-project-id":
        return False

    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)

    try:
        import google.auth
        from opentelemetry import trace
        from google.adk.telemetry.google_cloud import get_gcp_exporters, get_gcp_resource
        from google.adk.telemetry.setup import maybe_set_otel_providers

        credentials, default_proj = google.auth.default()
        effective_project = project_id or default_proj

        otel_hooks = get_gcp_exporters(
            enable_cloud_tracing=True,
            enable_cloud_metrics=False,
            enable_cloud_logging=False,
            google_auth=(credentials, effective_project),
        )
        otel_resource = get_gcp_resource(effective_project)
        maybe_set_otel_providers(
            otel_hooks_to_setup=[otel_hooks],
            otel_resource=otel_resource,
        )

        try:
            from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor

            GoogleGenAiSdkInstrumentor().instrument()
        except Exception:
            pass

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except Exception:
            pass

        def _flush_traces() -> None:
            try:
                provider = trace.get_tracer_provider()
                if hasattr(provider, "force_flush"):
                    provider.force_flush(timeout_millis=5000)
            except Exception:
                pass

        atexit.register(_flush_traces)
        _OTEL_INITIALIZED = True
        return True
    except Exception as exc:
        logger.debug("Cloud Trace OpenTelemetry setup skipped for %s: %s", service_name, exc)
        return False


class SharedVertexAiMemoryBankService(VertexAiMemoryBankService):
    """Pins Memory Bank scope's `app_name` to `travel_concierge` across all 16
    microservices so facts saved by one agent can be recalled by any other agent.
    """

    async def search_memory(self, *, app_name: str, user_id: str, query: str):
        return await super().search_memory(
            app_name=SHARED_MEMORY_APP_NAME, user_id=user_id, query=query
        )

    async def add_memory(self, *, app_name: str, user_id: str, memories, custom_metadata=None):
        return await super().add_memory(
            app_name=SHARED_MEMORY_APP_NAME,
            user_id=user_id,
            memories=memories,
            custom_metadata=custom_metadata,
        )

    async def add_session_to_memory(self, session):
        session_copy = session.model_copy(update={"app_name": SHARED_MEMORY_APP_NAME})
        return await super().add_session_to_memory(session_copy)


class SharedInMemoryMemoryService(InMemoryMemoryService):
    """In-memory Memory Bank service used when running locally (`LOCAL_MODE=true`).
    Pins `app_name` to `travel_concierge` and bridges `add_memory` -> `add_events_to_memory`
    so direct facts added via `memorize` and `save_preference` are searchable via
    `search_memory`.
    """

    async def search_memory(self, *, app_name: str, user_id: str, query: str):
        return await super().search_memory(
            app_name=SHARED_MEMORY_APP_NAME, user_id=user_id, query=query
        )

    async def add_events_to_memory(
        self, *, app_name: str, user_id: str, events, session_id: str | None = None, custom_metadata=None
    ):
        return await super().add_events_to_memory(
            app_name=SHARED_MEMORY_APP_NAME,
            user_id=user_id,
            events=events,
            session_id=session_id,
            custom_metadata=custom_metadata,
        )

    async def add_memory(self, *, app_name: str, user_id: str, memories, custom_metadata=None):
        from google.adk.events.event import Event

        events = [
            Event(author=getattr(m, "author", None) or "user", content=m.content)
            for m in memories
            if getattr(m, "content", None) is not None
        ]
        return await super().add_events_to_memory(
            app_name=SHARED_MEMORY_APP_NAME,
            user_id=user_id,
            events=events,
            custom_metadata=custom_metadata,
        )

    async def add_session_to_memory(self, session):
        session_copy = session.model_copy(update={"app_name": SHARED_MEMORY_APP_NAME})
        return await super().add_session_to_memory(session_copy)


_LOCAL_SESSION_SERVICE: InMemorySessionService | None = None
_LOCAL_MEMORY_SERVICE: SharedInMemoryMemoryService | None = None


def _location() -> str:
    return os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")


def build_session_service():
    """Returns `InMemorySessionService` in local mode or `VertexAiSessionService` in cloud mode."""
    global _LOCAL_SESSION_SERVICE
    if is_local_mode():
        if _LOCAL_SESSION_SERVICE is None:
            _LOCAL_SESSION_SERVICE = InMemorySessionService()
        return _LOCAL_SESSION_SERVICE
    return VertexAiSessionService(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=_location(),
        agent_engine_id=os.environ["SESSION_AGENT_ENGINE_ID"],
    )


def build_memory_service():
    """Returns `SharedInMemoryMemoryService` in local mode or `SharedVertexAiMemoryBankService` in cloud mode."""
    global _LOCAL_MEMORY_SERVICE
    if is_local_mode():
        if _LOCAL_MEMORY_SERVICE is None:
            _LOCAL_MEMORY_SERVICE = SharedInMemoryMemoryService()
        return _LOCAL_MEMORY_SERVICE
    return SharedVertexAiMemoryBankService(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=_location(),
        agent_engine_id=os.environ["MEMORY_AGENT_ENGINE_ID"],
    )


def build_bigquery_analytics_plugin(agent_name: str, framework: str = "google_adk") -> list:
    """Builds the ADK `BigQueryAgentAnalyticsPlugin` for streaming agent events
    to BigQuery and visualizing in the Looker Marketplace Agent Analytics Block.
    """
    if is_local_mode() and os.environ.get("BQ_ENABLE_IN_LOCAL", "false").strip().lower() not in ("1", "true", "yes"):
        # Stateless local mode: do not connect to BigQuery when running locally
        return []
    enabled_str = os.environ.get("BQ_ANALYTICS_ENABLED", "true").strip().lower()
    if enabled_str in ("0", "false", "no", "off"):
        return []

    project_id = (
        os.environ.get("BQ_ANALYTICS_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or ""
    ).strip()
    if not project_id or project_id == "your-gcp-project-id":
        return []

    dataset_id = os.environ.get("BQ_ANALYTICS_DATASET_ID", "agent_analytics").strip()
    table_id = os.environ.get("BQ_ANALYTICS_TABLE_ID", "agent_events").strip()
    location = os.environ.get("BQ_ANALYTICS_LOCATION", "US").strip()
    gcs_bucket = os.environ.get("BQ_ANALYTICS_GCS_BUCKET", "").strip() or None

    try:
        from google.adk.plugins.bigquery_agent_analytics_plugin import (
            BigQueryAgentAnalyticsPlugin,
            BigQueryLoggerConfig,
        )

        config = BigQueryLoggerConfig(
            enabled=True,
            table_id=table_id,
            create_views=True,
            auto_schema_upgrade=True,
            log_multi_modal_content=True,
            log_session_metadata=True,
            enable_otel_correlation=True,
            custom_tags={
                "framework": framework,
                "agent_service": agent_name,
                "app": SHARED_MEMORY_APP_NAME,
            },
            gcs_bucket_name=gcs_bucket,
        )
        plugin = BigQueryAgentAnalyticsPlugin(
            project_id=project_id,
            dataset_id=dataset_id,
            table_id=table_id,
            location=location,
            config=config,
        )
        return [plugin]
    except Exception as exc:
        logger.debug("BigQueryAgentAnalyticsPlugin not initialized for %s: %s", agent_name, exc)
        return []
