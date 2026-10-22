"""Builders for Session Service, Memory Bank, OpenTelemetry Cloud Trace Exporter,
and BigQuery Agent Analytics Plugin.

Supports two execution modes automatically:
1. **Cloud / Vertex AI Mode** (when `LOCAL_MODE` is false and `SESSION_AGENT_ENGINE_ID`
   + `MEMORY_AGENT_ENGINE_ID` are configured):
   - Uses ADK's built-in `VertexAiSessionService` (`SESSION_AGENT_ENGINE_ID`)
   - Uses `SharedVertexAiMemoryBankService` (`MEMORY_AGENT_ENGINE_ID`) pinned to
     `app_name="travel_concierge"` across all 16 agents.
2. **Local / Docker Mode** (when `LOCAL_MODE=true` or `SESSION_AGENT_ENGINE_ID` /
   `MEMORY_AGENT_ENGINE_ID` are unset):
   - Uses ADK's built-in `InMemorySessionService`
   - Uses `SharedInMemoryMemoryService` (`InMemoryMemoryService` pinned to
     `app_name="travel_concierge"`).

All services, OpenTelemetry exporters, and BigQuery analytics plugins are eagerly
initialized at module import time to avoid lazy-loading latency.
"""

import atexit
from contextvars import ContextVar
import logging
import os

os.environ.setdefault("GRPC_DNS_RESOLVER", "native")
os.environ.setdefault("OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT", "16000")
os.environ.setdefault("OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT", "16000")

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)
# Always route Gemini / GenAI model calls to the global endpoint, even when
# Vertex AI Agent Engine injects GOOGLE_CLOUD_LOCATION=us-central1 at runtime.
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["VERTEXAI_LOCATION"] = "global"

import socket as _socket

_orig_getaddrinfo = _socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    res = _orig_getaddrinfo(host, port, family, type, proto, flags)
    ipv4 = [r for r in res if r[0] == _socket.AF_INET]
    return ipv4 if ipv4 else res


_socket.getaddrinfo = _ipv4_getaddrinfo

from google.adk.memory import InMemoryMemoryService, VertexAiMemoryBankService
from google.adk.sessions import InMemorySessionService, VertexAiSessionService
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

logger = logging.getLogger(__name__)

SHARED_MEMORY_APP_NAME = "travel_concierge"
AGENT_SERVICE_NAME = "in_trip_agent"
os.environ["OTEL_SERVICE_NAME"] = AGENT_SERVICE_NAME
_OTEL_INITIALIZED = False
current_traceparent: ContextVar[str] = ContextVar("current_traceparent", default="")


def format_current_traceparent() -> str:
    """Formats the active OpenTelemetry span into a W3C `traceparent` string
    (`00-<32-hex-trace-id>-<16-hex-span-id>-<2-hex-flags>`).
    """
    try:
        span = trace.get_current_span()
        if span is not None:
            sc = span.get_span_context()
            if sc and sc.is_valid:
                flags = int(sc.trace_flags) if sc.trace_flags is not None else 1
                return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-{flags:02x}"
    except Exception:
        pass
    return current_traceparent.get() or ""


def extract_otel_context_from_traceparent(traceparent_str: str | None):
    """Parses a W3C `traceparent` header or metadata value into an OpenTelemetry
    `Context` whose current span is the remote caller's span, linking child spans
    across A2A agent invocations under the same `trace_id` and `parent_span_id`.
    """
    if not traceparent_str or not isinstance(traceparent_str, str):
        return None
    try:
        parts = traceparent_str.strip().split("-")
        if len(parts) >= 4 and len(parts[1]) == 32 and len(parts[2]) == 16:
            trace_id = int(parts[1], 16)
            span_id = int(parts[2], 16)
            flags = int(parts[3], 16) if len(parts[3]) == 2 else 1
            if trace_id and span_id:
                parent_sc = SpanContext(
                    trace_id=trace_id,
                    span_id=span_id,
                    is_remote=True,
                    trace_flags=TraceFlags(flags or 1),
                )
                return trace.set_span_in_context(NonRecordingSpan(parent_sc))
    except Exception:
        pass
    return None


def is_local_mode() -> bool:
    """Returns True when running locally/Docker with in-memory session & memory bank."""
    if os.environ.get("LOCAL_MODE", "").strip().lower() in ("1", "true", "yes"):
        return True
    if not os.environ.get("SESSION_AGENT_ENGINE_ID") or not os.environ.get("MEMORY_AGENT_ENGINE_ID"):
        return True
    return False


def setup_cloud_trace_telemetry(service_name: str = AGENT_SERVICE_NAME) -> bool:
    """Configures OpenTelemetry to export all ADK, GenAI SDK, and HTTPX A2A
    traces to Google Cloud Trace (`telemetry.googleapis.com/v1/traces`),
    including during `adk eval` runs.
    """
    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return True

    if is_local_mode() and os.environ.get("OTEL_ENABLE_IN_LOCAL", "false").strip().lower() not in ("1", "true", "yes"):
        try:
            from opentelemetry.sdk.resources import Resource as _OtelResource
            from opentelemetry.sdk.trace import TracerProvider

            if not isinstance(trace.get_tracer_provider(), TracerProvider):
                trace.set_tracer_provider(
                    TracerProvider(resource=_OtelResource(attributes={"service.name": service_name}))
                )
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

    os.environ["OTEL_SERVICE_NAME"] = service_name

    try:
        import google.auth
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
        from opentelemetry.sdk.resources import Resource as _OtelResource
        from opentelemetry.sdk.trace import SpanLimits as _SpanLimits, TracerProvider as _SdkTracerProvider

        otel_resource = get_gcp_resource(effective_project).merge(
            _OtelResource(attributes={"service.name": service_name})
        )
        current_provider = trace.get_tracer_provider()
        if isinstance(current_provider, _SdkTracerProvider):
            try:
                current_provider._resource = current_provider._resource.merge(otel_resource)
                current_provider._span_limits = _SpanLimits(
                    max_attribute_length=16000, max_span_attribute_length=16000
                )
            except Exception:
                pass
            for sp in otel_hooks.span_processors:
                current_provider.add_span_processor(sp)
        else:
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
_CLOUD_SESSION_SERVICE: VertexAiSessionService | None = None
_LOCAL_MEMORY_SERVICE: SharedInMemoryMemoryService | None = None
_CLOUD_MEMORY_SERVICE: SharedVertexAiMemoryBankService | None = None
_BQ_PLUGIN_CACHE: dict[str, list] = {}


def _location() -> str:
    return os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")


def build_session_service():
    """Returns ADK's built-in `InMemorySessionService` (local mode) or
    `VertexAiSessionService` (cloud mode) singleton.
    """
    global _LOCAL_SESSION_SERVICE, _CLOUD_SESSION_SERVICE
    if is_local_mode():
        if _LOCAL_SESSION_SERVICE is None:
            _LOCAL_SESSION_SERVICE = InMemorySessionService()
        return _LOCAL_SESSION_SERVICE
    if _CLOUD_SESSION_SERVICE is None:
        _CLOUD_SESSION_SERVICE = VertexAiSessionService(
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=_location(),
            agent_engine_id=os.environ["SESSION_AGENT_ENGINE_ID"],
        )
    return _CLOUD_SESSION_SERVICE


def build_memory_service():
    """Returns the pre-initialized `SharedInMemoryMemoryService` (local mode) or
    `SharedVertexAiMemoryBankService` (cloud mode) singleton.
    """
    global _LOCAL_MEMORY_SERVICE, _CLOUD_MEMORY_SERVICE
    if is_local_mode():
        if _LOCAL_MEMORY_SERVICE is None:
            _LOCAL_MEMORY_SERVICE = SharedInMemoryMemoryService()
        return _LOCAL_MEMORY_SERVICE
    if _CLOUD_MEMORY_SERVICE is None:
        _CLOUD_MEMORY_SERVICE = SharedVertexAiMemoryBankService(
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=_location(),
            agent_engine_id=os.environ["MEMORY_AGENT_ENGINE_ID"],
        )
    return _CLOUD_MEMORY_SERVICE


def build_bigquery_analytics_plugin(agent_name: str, framework: str = "google_adk") -> list:
    """Builds and caches the ADK `BigQueryAgentAnalyticsPlugin` for streaming agent
    events to BigQuery and visualizing in the Looker Marketplace Agent Analytics Block.
    """
    if is_local_mode() and os.environ.get("BQ_ENABLE_IN_LOCAL", "false").strip().lower() not in ("1", "true", "yes"):
        return []
    enabled_str = os.environ.get("BQ_ANALYTICS_ENABLED", "true").strip().lower()
    if enabled_str in ("0", "false", "no", "off"):
        return []

    cache_key = f"{agent_name}:{framework}"
    if cache_key in _BQ_PLUGIN_CACHE:
        return _BQ_PLUGIN_CACHE[cache_key]

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
            create_views=False,
            auto_schema_upgrade=False,
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
        _BQ_PLUGIN_CACHE[cache_key] = [plugin]
        return _BQ_PLUGIN_CACHE[cache_key]
    except Exception as exc:
        logger.debug("BigQueryAgentAnalyticsPlugin not initialized for %s: %s", agent_name, exc)
        return []


# Eagerly initialize OpenTelemetry, SessionService, and MemoryBankService at import time
setup_cloud_trace_telemetry(AGENT_SERVICE_NAME)
SESSION_SERVICE = build_session_service()
MEMORY_SERVICE = build_memory_service()
