"""Shared Vertex AI Session Service, Memory Bank, Cloud Trace, and BigQuery
Agent Analytics helpers for the LangGraph `booking_agent`.
"""

import atexit
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
import socket as _socket
import time
import uuid
import warnings

from dotenv import find_dotenv, load_dotenv
from opentelemetry import trace
import vertexai

load_dotenv(find_dotenv(usecwd=True), override=False)

_orig_getaddrinfo = _socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    res = _orig_getaddrinfo(host, port, family, type, proto, flags)
    ipv4 = [r for r in res if r[0] == _socket.AF_INET]
    return ipv4 if ipv4 else res


_socket.getaddrinfo = _ipv4_getaddrinfo

try:
    from copy import deepcopy as _deepcopy
    from google.genai._api_client import BaseApiClient

    BaseApiClient._use_aiohttp = lambda self: False
    if not getattr(BaseApiClient, "_fast_fallback_patched", False):
        _orig_async_req_once = BaseApiClient._async_request_once
        _orig_sync_req_once = BaseApiClient._request_once
        _fallback_until = 0.0
        _target_m = "gemini-" + "3" + "-flash-preview"

        def _make_fallback_req(http_request):
            req = _deepcopy(http_request)
            req.url = (req.url or "").replace(_target_m, "gemini-2.5-flash")
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
            if is_gen and _target_m in url:
                if time.monotonic() < _fallback_until:
                    return await _orig_async_req_once(self, _make_fallback_req(http_request), stream=stream)
                primary = _deepcopy(http_request)
                primary.timeout = 25.0
                try:
                    return await _orig_async_req_once(self, primary, stream=stream)
                except Exception:
                    _fallback_until = time.monotonic() + 30.0
                    return await _orig_async_req_once(self, _make_fallback_req(http_request), stream=stream)
            return await _orig_async_req_once(self, http_request, stream=stream)

        def _fast_sync_request_once(self, http_request, stream=False):
            global _fallback_until
            url = http_request.url or ""
            is_gen = ":generateContent" in url or ":streamGenerateContent" in url
            if is_gen and "/locations/us-central1/publishers/google/models/gemini-3" in url:
                url = url.replace("us-central1-aiplatform.googleapis.com", "aiplatform.googleapis.com").replace("/locations/us-central1/publishers/google/models/", "/locations/global/publishers/google/models/")
                http_request.url = url
            if is_gen and _target_m in url:
                if time.monotonic() < _fallback_until:
                    return _orig_sync_req_once(self, _make_fallback_req(http_request), stream=stream)
                primary = _deepcopy(http_request)
                primary.timeout = 25.0
                try:
                    return _orig_sync_req_once(self, primary, stream=stream)
                except Exception:
                    _fallback_until = time.monotonic() + 30.0
                    return _orig_sync_req_once(self, _make_fallback_req(http_request), stream=stream)
            return _orig_sync_req_once(self, http_request, stream=stream)

        BaseApiClient._async_request_once = _fast_async_request_once
        BaseApiClient._request_once = _fast_sync_request_once
        BaseApiClient._fast_fallback_patched = True
except Exception:
    pass

warnings.filterwarnings(
    "ignore", message="The vertexai.Client class is deprecated.*", category=FutureWarning
)

logger = logging.getLogger(__name__)

SHARED_APP_NAME = "travel_concierge"
current_user_id: ContextVar[str] = ContextVar("current_user_id", default="default_user")

_SESSION_ID_BY_CONTEXT: dict[str, str] = {}
_LOCAL_SESSIONS: dict[str, dict] = {}
_LOCAL_MEMORIES: dict[str, list[str]] = {}
_OTEL_INITIALIZED: bool = False


def is_local_mode() -> bool:
    """Returns True when running locally with in-memory session & memory bank."""
    if os.environ.get("LOCAL_MODE", "").strip().lower() in ("1", "true", "yes"):
        return True
    if not os.environ.get("SESSION_AGENT_ENGINE_ID") or not os.environ.get("MEMORY_AGENT_ENGINE_ID"):
        return True
    return False


def setup_cloud_trace_telemetry(service_name: str = "booking_agent") -> bool:
    """Configures OpenTelemetry to export LangGraph spans to Google Cloud Trace."""
    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return True
    if is_local_mode() and os.environ.get("OTEL_ENABLE_IN_LOCAL", "false").strip().lower() not in ("1", "true", "yes"):
        return False
    if os.environ.get("OTEL_TO_CLOUD", "true").strip().lower() in ("0", "false", "no", "off"):
        return False
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project_id or project_id == "your-gcp-project-id":
        return False
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    try:
        import google.auth
        from google.adk.telemetry.google_cloud import get_gcp_exporters, get_gcp_resource
        from google.adk.telemetry.setup import maybe_set_otel_providers

        credentials, default_proj = google.auth.default()
        eff_proj = project_id or default_proj
        hooks = get_gcp_exporters(enable_cloud_tracing=True, google_auth=(credentials, eff_proj))
        maybe_set_otel_providers(
            otel_hooks_to_setup=[hooks],
            otel_resource=get_gcp_resource(eff_proj),
        )
        atexit.register(
            lambda: getattr(trace.get_tracer_provider(), "force_flush", lambda **_: None)(timeout_millis=5000)
        )
        _OTEL_INITIALIZED = True
        return True
    except Exception as exc:
        logger.debug("LangGraph Cloud Trace setup skipped: %s", exc)
        return False


def _get_async_client():
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
    return vertexai.Client(project=project, location=location).aio


def _get_sync_client():
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
    return vertexai.Client(project=project, location=location)


async def load_or_create_vertex_session(
    context_id: str, user_id: str
) -> tuple[str, list[tuple[str, str]], dict]:
    """Loads or creates a session in `InMemory` (local mode) or `SESSION_AGENT_ENGINE_ID` (cloud mode)."""
    if is_local_mode():
        sess = _LOCAL_SESSIONS.get(context_id)
        if not sess:
            sess = {
                "session_id": f"local-lg-{context_id}",
                "user_id": user_id,
                "messages": [],
                "state": {"context_id": context_id, "agent": "booking_agent"},
            }
            _LOCAL_SESSIONS[context_id] = sess
        return sess["session_id"], list(sess["messages"]), dict(sess["state"])

    session_engine_id = os.environ["SESSION_AGENT_ENGINE_ID"]
    parent = f"reasoningEngines/{session_engine_id}"
    async_client = _get_async_client()

    session_id = _SESSION_ID_BY_CONTEXT.get(context_id)
    if session_id:
        session_name = f"{parent}/sessions/{session_id}"
        try:
            sess = await async_client.agent_engines.sessions.get(name=session_name)
            events_iter = await async_client.agent_engines.sessions.events.list(name=session_name)
            messages: list[tuple[str, str]] = []
            async for ev in events_iter:
                content = getattr(ev, "content", None)
                parts = getattr(content, "parts", None) or []
                role = "user" if getattr(content, "role", "user") == "user" else "assistant"
                for p in parts:
                    text = getattr(p, "text", None)
                    if text:
                        messages.append((role, text))
            state = getattr(sess, "session_state", None) or {}
            return session_id, messages, state
        except Exception:
            pass

    op = await async_client.agent_engines.sessions.create(
        name=parent,
        user_id=user_id,
        config={"session_state": {"context_id": context_id, "agent": "booking_agent"}},
    )
    created_name = op.response.name
    session_id = created_name.rsplit("/", 1)[-1]
    _SESSION_ID_BY_CONTEXT[context_id] = session_id
    return session_id, [], {"context_id": context_id, "agent": "booking_agent"}


async def append_vertex_session_turn(
    session_id: str,
    user_query: str,
    agent_reply: str,
    state_delta: dict | None = None,
    context_id: str | None = None,
) -> None:
    """Appends the user turn and assistant reply to local memory (local mode) or Vertex AI Session Service."""
    if is_local_mode():
        cid = context_id or session_id.replace("local-lg-", "")
        sess = _LOCAL_SESSIONS.setdefault(
            cid,
            {
                "session_id": session_id,
                "user_id": current_user_id.get(),
                "messages": [],
                "state": {"context_id": cid, "agent": "booking_agent"},
            },
        )
        sess["messages"].append(("user", user_query))
        sess["messages"].append(("assistant", agent_reply))
        if state_delta:
            sess["state"].update(state_delta)
        return

    session_engine_id = os.environ["SESSION_AGENT_ENGINE_ID"]
    session_name = f"reasoningEngines/{session_engine_id}/sessions/{session_id}"
    async_client = _get_async_client()
    now = datetime.now(tz=timezone.utc)

    await async_client.agent_engines.sessions.events.append(
        name=session_name,
        author="user",
        invocation_id=uuid.uuid4().hex,
        timestamp=now,
        config={"content": {"role": "user", "parts": [{"text": user_query}]}},
    )

    reply_config: dict = {"content": {"role": "model", "parts": [{"text": agent_reply}]}}
    if state_delta:
        reply_config["actions"] = {"state_delta": state_delta}

    await async_client.agent_engines.sessions.events.append(
        name=session_name,
        author="booking_agent",
        invocation_id=uuid.uuid4().hex,
        timestamp=datetime.now(tz=timezone.utc),
        config=reply_config,
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
    client.agent_engines.memories.generate(
        name=f"reasoningEngines/{memory_engine_id}",
        direct_memories_source={"direct_memories": [{"fact": fact}]},
        scope={"app_name": SHARED_APP_NAME, "user_id": uid},
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


def log_langgraph_run_to_bigquery(
    session_id: str,
    user_id: str,
    user_query: str,
    agent_reply: str,
    latency_ms: int,
) -> None:
    """Streams LangGraph `booking_agent` events to BigQuery (`agent_analytics.agent_events`)
    in the exact ADK BigQueryAgentAnalyticsPlugin V2 schema for Looker visualization.
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
        from google.cloud import bigquery

        client = bigquery.Client(project=project_id)
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        invocation_id = uuid.uuid4().hex
        trace_id = uuid.uuid4().hex
        root_span_id = uuid.uuid4().hex[:16]
        attrs = json.dumps(
            {
                "custom_tags": {
                    "framework": "langgraph",
                    "agent_service": "booking_agent",
                    "app": SHARED_APP_NAME,
                }
            }
        )
        rows = [
            {
                "timestamp": now_iso,
                "event_id": uuid.uuid4().hex,
                "event_type": "USER_MESSAGE_RECEIVED",
                "agent": "booking_agent",
                "session_id": session_id,
                "invocation_id": invocation_id,
                "user_id": user_id,
                "trace_id": trace_id,
                "span_id": root_span_id,
                "parent_span_id": None,
                "content": json.dumps({"text_summary": user_query[:4000]}),
                "attributes": attrs,
                "latency_ms": 0,
                "status": "OK",
            },
            {
                "timestamp": now_iso,
                "event_id": uuid.uuid4().hex,
                "event_type": "AGENT_COMPLETED",
                "agent": "booking_agent",
                "session_id": session_id,
                "invocation_id": invocation_id,
                "user_id": user_id,
                "trace_id": trace_id,
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
        logger.debug("LangGraph BigQuery analytics log skipped: %s", exc)
