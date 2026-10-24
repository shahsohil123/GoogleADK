"""Shared Vertex AI Session Service, Memory Bank, Cloud Trace, and BigQuery
Agent Analytics helpers for the CrewAI `pre_trip_agent`.

All services (`SESSION_SERVICE`, OpenTelemetry exporter, Vertex AI client, and
BigQuery client) are eagerly initialized at module import time.
"""

import atexit
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
import socket as _socket
import uuid
import warnings

os.environ.setdefault("GRPC_DNS_RESOLVER", "native")
os.environ.setdefault("OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT", "16000")
os.environ.setdefault("OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT", "16000")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "true")

from dotenv import find_dotenv, load_dotenv
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.sessions import BaseSessionService, InMemorySessionService, VertexAiSessionService
from google.genai import types
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
import vertexai

load_dotenv(find_dotenv(usecwd=True), override=False)
# Always route Gemini / GenAI model calls to the global endpoint, even when
# Vertex AI Agent Engine injects GOOGLE_CLOUD_LOCATION=us-central1 at runtime.
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["VERTEXAI_LOCATION"] = "global"

_orig_getaddrinfo = _socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    res = _orig_getaddrinfo(host, port, family, type, proto, flags)
    ipv4 = [r for r in res if r[0] == _socket.AF_INET]
    return ipv4 if ipv4 else res


_socket.getaddrinfo = _ipv4_getaddrinfo

warnings.filterwarnings(
    "ignore", message="The vertexai.Client class is deprecated.*", category=FutureWarning
)

logger = logging.getLogger(__name__)

SHARED_APP_NAME = "travel_concierge"
AGENT_APP_NAME = "pre_trip_agent"
AGENT_SERVICE_NAME = "pre_trip_agent"
os.environ["OTEL_SERVICE_NAME"] = AGENT_SERVICE_NAME
current_user_id: ContextVar[str] = ContextVar("current_user_id", default="default_user")
current_traceparent: ContextVar[str] = ContextVar("current_traceparent", default="")

_LOCAL_SESSION_SERVICE: InMemorySessionService | None = None
_CLOUD_SESSION_SERVICE: VertexAiSessionService | None = None
_VERTEX_SYNC_CLIENT = None
_BQ_CLIENT = None
_LOCAL_MEMORIES: dict[str, list[str]] = {}
_OTEL_INITIALIZED: bool = False


def extract_otel_context_from_traceparent(traceparent_str: str | None):
    """Parses a W3C `traceparent` header or metadata value into an OpenTelemetry
    `Context` whose current span is the remote caller's span.
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
    """Returns True when running locally with in-memory session & memory bank."""
    if os.environ.get("LOCAL_MODE", "").strip().lower() in ("1", "true", "yes"):
        return True
    if not os.environ.get("SESSION_AGENT_ENGINE_ID") or not os.environ.get("MEMORY_AGENT_ENGINE_ID"):
        return True
    return False


class SharedVertexAiSessionService(VertexAiSessionService):
    """Fetches `session.state` via `GetSessionConfig(num_recent_events=0)` without
    downloading hundreds of historical events (`sessions.events.list`) on every
    invocation, and caches `get_session` briefly to avoid duplicate round-trips.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._recent_session_cache: dict[tuple[str, str], tuple[float, object]] = {}

    async def get_session(self, *, app_name: str, user_id: str, session_id: str, config=None):
        import time
        from google.adk.sessions.base_session_service import GetSessionConfig

        cache_key = (user_id, session_id)
        now = time.monotonic()
        cached = self._recent_session_cache.get(cache_key)
        if cached is not None and (now - cached[0]) < 2.5:
            return cached[1].model_copy(deep=True)

        session = await super().get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            config=GetSessionConfig(num_recent_events=0),
        )
        if session is not None:
            self._recent_session_cache[cache_key] = (
                time.monotonic(),
                session.model_copy(deep=True),
            )
        return session

    async def create_session(self, *, app_name: str, user_id: str, state=None, session_id=None):
        import time

        session = await super().create_session(
            app_name=app_name,
            user_id=user_id,
            state=state,
            session_id=session_id,
        )
        if session is not None:
            self._recent_session_cache[(user_id, session.id)] = (
                time.monotonic(),
                session.model_copy(deep=True),
            )
        return session

    async def append_event(self, session, event):
        self._recent_session_cache.pop((session.user_id, session.id), None)
        return await super().append_event(session=session, event=event)


def build_session_service() -> BaseSessionService:
    """Returns ADK's built-in `InMemorySessionService` (local mode) or
    `SharedVertexAiSessionService` (cloud mode) singleton.
    """
    global _LOCAL_SESSION_SERVICE, _CLOUD_SESSION_SERVICE
    if is_local_mode():
        if _LOCAL_SESSION_SERVICE is None:
            _LOCAL_SESSION_SERVICE = InMemorySessionService()
        return _LOCAL_SESSION_SERVICE
    if _CLOUD_SESSION_SERVICE is None:
        _CLOUD_SESSION_SERVICE = SharedVertexAiSessionService(
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1"),
            agent_engine_id=os.environ["SESSION_AGENT_ENGINE_ID"],
        )
    return _CLOUD_SESSION_SERVICE


def _wire_crewai_telemetry_to_otel_provider() -> None:
    """Routes CrewAI's built-in OpenTelemetry `Telemetry` spans (`Crew Execution`,
    `Crew Created`, `Task Created`, `Tool Usage`) to the active OpenTelemetry
    `TracerProvider` (Google Cloud Trace).
    """
    try:
        from crewai.telemetry import Telemetry

        crew_telemetry = Telemetry()
        crew_telemetry.provider = trace.get_tracer_provider()
        crew_telemetry.ready = True
        crew_telemetry.trace_set = True
    except Exception:
        pass


def setup_cloud_trace_telemetry(service_name: str = "pre_trip_agent") -> bool:
    """Configures OpenTelemetry to export CrewAI spans to Google Cloud Trace."""
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
            _wire_crewai_telemetry_to_otel_provider()
            _OTEL_INITIALIZED = True
        except Exception:
            pass
        return False
    if os.environ.get("OTEL_TO_CLOUD", "true").strip().lower() in ("0", "false", "no", "off"):
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
        eff_proj = project_id or default_proj
        hooks = get_gcp_exporters(enable_cloud_tracing=True, google_auth=(credentials, eff_proj))
        from opentelemetry.sdk.resources import Resource as _OtelResource
        from opentelemetry.sdk.trace import SpanLimits as _SpanLimits, TracerProvider as _SdkTracerProvider

        otel_resource = get_gcp_resource(eff_proj).merge(
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
            for sp in hooks.span_processors:
                current_provider.add_span_processor(sp)
        else:
            maybe_set_otel_providers(
                otel_hooks_to_setup=[hooks],
                otel_resource=otel_resource,
            )
        _wire_crewai_telemetry_to_otel_provider()
        atexit.register(
            lambda: getattr(trace.get_tracer_provider(), "force_flush", lambda **_: None)(timeout_millis=5000)
        )
        _OTEL_INITIALIZED = True
        return True
    except Exception as exc:
        logger.debug("CrewAI Cloud Trace setup skipped: %s", exc)
        return False


def _get_sync_client():
    global _VERTEX_SYNC_CLIENT
    if _VERTEX_SYNC_CLIENT is None:
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
        _VERTEX_SYNC_CLIENT = vertexai.Client(project=project, location=location)
    return _VERTEX_SYNC_CLIENT


def _get_bq_client(project_id: str):
    global _BQ_CLIENT
    if _BQ_CLIENT is None:
        from google.cloud import bigquery

        _BQ_CLIENT = bigquery.Client(project=project_id)
    return _BQ_CLIENT


async def _resolve_or_create_session(session_service: BaseSessionService, user_id: str, session_id: str | None):
    import time

    cache = getattr(session_service, "_recent_session_cache", None)
    if isinstance(cache, dict) and session_id:
        cached = cache.get((user_id, session_id))
        if cached is not None and (time.monotonic() - cached[0]) < 15.0:
            return cached[1].model_copy(deep=True)

    session = None
    if session_id:
        try:
            session = await session_service.get_session(
                app_name=AGENT_APP_NAME,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception:
            session = None
    if session is None and user_id:
        try:
            listed = await session_service.list_sessions(
                app_name=AGENT_APP_NAME,
                user_id=user_id,
            )
            if listed and listed.sessions:
                session = listed.sessions[-1]
        except Exception:
            session = None
    if session is None:
        try:
            session = await session_service.create_session(
                app_name=AGENT_APP_NAME,
                user_id=user_id,
                state={"context_id": session_id or "", "agent": AGENT_APP_NAME},
                session_id=session_id,
            )
        except Exception:
            session = await session_service.create_session(
                app_name=AGENT_APP_NAME,
                user_id=user_id,
                state={"context_id": session_id or "", "agent": AGENT_APP_NAME},
            )
    if isinstance(cache, dict) and session is not None and session_id:
        cache[(user_id, session_id)] = (time.monotonic(), session.model_copy(deep=True))
    return session


async def load_or_create_vertex_session(
    context_id: str, user_id: str
) -> tuple[str, list[str], dict]:
    """Loads or reuses the user's session via ADK's built-in SessionService."""
    session_service = build_session_service()
    session = await _resolve_or_create_session(session_service, user_id, context_id)
    history_lines: list[str] = []
    for ev in session.events:
        content = getattr(ev, "content", None)
        parts = getattr(content, "parts", None) or []
        role = "User" if getattr(content, "role", "user") == "user" else "Assistant"
        for p in parts:
            text = getattr(p, "text", None)
            if text:
                history_lines.append(f"{role}: {text}")
    return session.id, history_lines, dict(session.state or {})


async def append_vertex_session_turn(
    session_id: str,
    user_query: str,
    agent_reply: str,
    state_delta: dict | None = None,
    context_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Appends the user turn and assistant reply via ADK's built-in SessionService."""
    uid = user_id or current_user_id.get()
    sid = session_id or context_id
    session_service = build_session_service()
    session = await _resolve_or_create_session(session_service, uid, sid)
    inv_id = uuid.uuid4().hex
    await session_service.append_event(
        session=session,
        event=Event(
            invocation_id=inv_id,
            author="user",
            content=types.Content(role="user", parts=[types.Part.from_text(text=user_query)]),
        ),
    )
    await session_service.append_event(
        session=session,
        event=Event(
            invocation_id=inv_id,
            author=AGENT_APP_NAME,
            content=types.Content(role="model", parts=[types.Part.from_text(text=agent_reply)]),
            actions=EventActions(state_delta=state_delta or {}),
        ),
    )


def save_memory_fact_sync(fact: str, user_id: str | None = None) -> dict:
    """Saves a durable fact into in-memory Memory Bank (local mode) or Vertex AI Memory Bank."""
    uid = user_id or current_user_id.get()
    if is_local_mode():
        key = f"{SHARED_APP_NAME}/{uid}"
        _LOCAL_MEMORIES.setdefault(key, []).append(fact)
        return {"saved": True, "fact": fact, "user_id": uid, "mode": "in_memory"}

    memory_engine_id = os.environ["MEMORY_AGENT_ENGINE_ID"]
    client = _get_sync_client()
    client.agent_engines.memories.create(
        name=f"reasoningEngines/{memory_engine_id}",
        fact=fact,
        scope={"app_name": SHARED_APP_NAME, "user_id": uid},
        config={"wait_for_completion": False},
    )
    return {"saved": True, "fact": fact, "user_id": uid, "mode": "vertex_ai"}


def search_memory_facts_sync(query: str, user_id: str | None = None) -> list[str]:
    """Retrieves relevant facts for this user from in-memory Memory Bank (local mode) or Vertex AI Memory Bank."""
    uid = user_id or current_user_id.get()
    if is_local_mode():
        key = f"{SHARED_APP_NAME}/{uid}"
        facts = _LOCAL_MEMORIES.get(key, [])
        words = [w.lower() for w in query.split() if len(w) > 2]
        if not words:
            return list(facts)
        matched = [f for f in facts if any(w in f.lower() for w in words)]
        return matched or list(facts)

    memory_engine_id = os.environ["MEMORY_AGENT_ENGINE_ID"]
    client = _get_sync_client()
    results = client.agent_engines.memories.retrieve(
        name=f"reasoningEngines/{memory_engine_id}",
        scope={"app_name": SHARED_APP_NAME, "user_id": uid},
        similarity_search_params={"search_query": query},
    )
    facts: list[str] = []
    for item in results:
        mem = getattr(item, "memory", None)
        fact = getattr(mem, "fact", None) if mem else None
        if fact:
            facts.append(fact)
    return facts


def log_crewai_run_to_bigquery(
    session_id: str,
    user_id: str,
    user_query: str,
    agent_reply: str,
    latency_ms: int,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
) -> None:
    """Streams CrewAI `pre_trip_agent` events to BigQuery (`agent_analytics.agent_events`)
    in the exact ADK BigQueryAgentAnalyticsPlugin V2 schema for Looker visualization,
    preserving the caller's OpenTelemetry `trace_id`, `span_id`, and `parent_span_id`.
    """
    if is_local_mode() and os.environ.get("BQ_ENABLE_IN_LOCAL", "false").strip().lower() not in ("1", "true", "yes"):
        return
    enabled_str = os.environ.get("BQ_ANALYTICS_ENABLED", "true").strip().lower()
    if enabled_str in ("0", "false", "no", "off"):
        return

    project_id = (
        os.environ.get("BQ_ANALYTICS_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or ""
    ).strip()
    if not project_id or project_id == "your-gcp-project-id":
        return

    dataset_id = os.environ.get("BQ_ANALYTICS_DATASET_ID", "agent_analytics").strip()
    table_id = os.environ.get("BQ_ANALYTICS_TABLE_ID", "agent_events").strip()
    full_table_id = f"{project_id}.{dataset_id}.{table_id}"

    try:
        client = _get_bq_client(project_id)
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        invocation_id = uuid.uuid4().hex
        eff_trace_id = trace_id or uuid.uuid4().hex
        root_span_id = span_id or uuid.uuid4().hex[:16]
        attrs = json.dumps(
            {
                "custom_tags": {
                    "framework": "crewai",
                    "agent_service": "pre_trip_agent",
                    "app": SHARED_APP_NAME,
                }
            }
        )
        rows = [
            {
                "timestamp": now_iso,
                "event_id": uuid.uuid4().hex,
                "event_type": "USER_MESSAGE_RECEIVED",
                "agent": "pre_trip_agent",
                "session_id": session_id,
                "invocation_id": invocation_id,
                "user_id": user_id,
                "trace_id": eff_trace_id,
                "span_id": root_span_id,
                "parent_span_id": parent_span_id,
                "content": json.dumps({"text_summary": user_query[:4000]}),
                "attributes": attrs,
                "latency_ms": 0,
                "status": "OK",
            },
            {
                "timestamp": now_iso,
                "event_id": uuid.uuid4().hex,
                "event_type": "AGENT_COMPLETED",
                "agent": "pre_trip_agent",
                "session_id": session_id,
                "invocation_id": invocation_id,
                "user_id": user_id,
                "trace_id": eff_trace_id,
                "span_id": uuid.uuid4().hex[:16],
                "parent_span_id": root_span_id,
                "content": json.dumps({"text_summary": agent_reply[:4000]}),
                "attributes": attrs,
                "latency_ms": latency_ms,
                "status": "OK",
            },
        ]
        client.insert_rows_json(full_table_id, rows)
    except Exception as exc:
        logger.debug("CrewAI BigQuery analytics log skipped: %s", exc)


# Eagerly initialize OpenTelemetry, SessionService, and cloud clients at import time
setup_cloud_trace_telemetry(AGENT_SERVICE_NAME)
SESSION_SERVICE = build_session_service()
if not is_local_mode():
    try:
        _get_sync_client()
    except Exception:
        pass
    try:
        _proj = (
            os.environ.get("BQ_ANALYTICS_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or ""
        ).strip()
        if _proj and _proj != "your-gcp-project-id":
            _get_bq_client(_proj)
    except Exception:
        pass

_wire_crewai_telemetry_to_otel_provider()
