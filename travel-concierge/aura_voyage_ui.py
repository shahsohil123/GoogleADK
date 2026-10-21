"""AURA // VOYAGE — Polyglot A2UI & AG-UI Travel Concierge Studio.

A dedicated Agent-to-UI (A2UI) and Agentic Generative UI (AG-UI) web interface
for demonstrating the 16 Travel Concierge A2A agents across two environments:
  1. **Dev (GCP Agent Runtime — `.env.dev`)**:
     Points to the 16 deployed BYOC A2A containers in Vertex AI Agent Engine,
     Google Cloud Agent Registry, shared Vertex AI Session Engine & Memory Bank,
     Google Cloud Trace, and BigQuery -> Looker Agent Analytics.
  2. **Local (Docker A2A Setup — `.env`)**:
     Points to the local Docker Compose A2A containers (`:8000` local Agent
     Registry + `:8001`–`:8016` A2A agents) with in-memory session & memory bank.

Run:
    make ui          # Opens http://127.0.0.1:8090 (toggle Local Docker <-> Dev GCP Runtime in UI)
    make ui-local    # Starts defaulting to Local Docker Setup (.env)
    make ui-dev      # Starts defaulting to Dev GCP Agent Runtime (.env.dev)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

warnings.filterwarnings("ignore")
os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
os.environ["ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"

from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import google.auth
import google.auth.transport.requests
import httpx
import uvicorn

ROOT_DIR = Path(__file__).resolve().parent

# Read both .env (Local) and .env.dev (Dev / GCP Agent Runtime)
_LOCAL_ENV = dotenv_values(ROOT_DIR / ".env") if (ROOT_DIR / ".env").exists() else {}
_DEV_ENV = dotenv_values(ROOT_DIR / ".env.dev") if (ROOT_DIR / ".env.dev").exists() else {}
load_dotenv(ROOT_DIR / ".env", override=False)

DEFAULT_ENV_MODE = os.environ.get("AURA_DEFAULT_MODE", "dev")  # "dev" or "local"
DEFAULT_TRAVELER = os.environ.get("TRAVELER_NAME", "sohil")
for _p in (str(ROOT_DIR), str(ROOT_DIR / "root_agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

AGENT_SPECS: List[Dict[str, Any]] = [
    {"dir": "root_agent", "id": "root-concierge-agent-a2a", "name": "root_agent", "label": "Root Concierge", "framework": "Google ADK", "port": 8001, "rpc_path": "/a2a"},
    {"dir": "inspiration_agent", "id": "inspiration-agent-a2a", "name": "inspiration_agent", "label": "Inspiration Service", "framework": "Google ADK", "port": 8002, "rpc_path": "/a2a"},
    {"dir": "planning_agent", "id": "planning-agent-a2a", "name": "planning_agent", "label": "Planning Service", "framework": "Google ADK", "port": 8003, "rpc_path": "/a2a"},
    {"dir": "booking_agent", "id": "booking-agent-a2a", "name": "booking_agent", "label": "Booking & Payments", "framework": "LangGraph", "port": 8004, "rpc_path": "/"},
    {"dir": "pre_trip_agent", "id": "pre-trip-agent-a2a", "name": "pre_trip_agent", "label": "Pre-Trip Readiness", "framework": "CrewAI", "port": 8005, "rpc_path": "/"},
    {"dir": "in_trip_agent", "id": "in-trip-agent-a2a", "name": "in_trip_agent", "label": "In-Trip Service", "framework": "Google ADK", "port": 8006, "rpc_path": "/a2a"},
    {"dir": "post_trip_agent", "id": "post-trip-agent-a2a", "name": "post_trip_agent", "label": "Post-Trip & Memory", "framework": "Google ADK", "port": 8007, "rpc_path": "/a2a"},
    {"dir": "place_agent", "id": "place-agent-a2a", "name": "place_agent", "label": "Place Ideas", "framework": "Google ADK", "port": 8008, "rpc_path": "/a2a"},
    {"dir": "poi_agent", "id": "poi-agent-a2a", "name": "poi_agent", "label": "POI Explorer", "framework": "Google ADK", "port": 8009, "rpc_path": "/a2a"},
    {"dir": "flight_search_agent", "id": "flight-search-agent-a2a", "name": "flight_search_agent", "label": "Flight Search", "framework": "Google ADK", "port": 8010, "rpc_path": "/a2a"},
    {"dir": "flight_seat_selection_agent", "id": "flight-seat-selection-agent-a2a", "name": "flight_seat_selection_agent", "label": "Seat Selection", "framework": "Google ADK", "port": 8011, "rpc_path": "/a2a"},
    {"dir": "hotel_search_agent", "id": "hotel-search-agent-a2a", "name": "hotel_search_agent", "label": "Hotel Search", "framework": "Google ADK", "port": 8012, "rpc_path": "/a2a"},
    {"dir": "hotel_room_selection_agent", "id": "hotel-room-selection-agent-a2a", "name": "hotel_room_selection_agent", "label": "Room Selection", "framework": "Google ADK", "port": 8013, "rpc_path": "/a2a"},
    {"dir": "itinerary_agent", "id": "itinerary-agent-a2a", "name": "itinerary_agent", "label": "Itinerary Builder", "framework": "Google ADK", "port": 8014, "rpc_path": "/a2a"},
    {"dir": "day_of_agent", "id": "day-of-agent-a2a", "name": "day_of_agent", "label": "Day-Of Transit", "framework": "Google ADK", "port": 8015, "rpc_path": "/a2a"},
    {"dir": "trip_monitor_agent", "id": "trip-monitor-agent-a2a", "name": "trip_monitor_agent", "label": "Flight & Delay Monitor", "framework": "Google ADK", "port": 8016, "rpc_path": "/a2a"},
]


async def _check_local_docker_Status() -> Tuple[bool, Set[int]]:
    """Check which local Docker containers (:8000 registry + :8001..:8016 agents) are live."""
    live_ports: Set[int] = set()
    async with httpx.AsyncClient(timeout=0.6) as client:
        ports = [8000] + [s["port"] for s in AGENT_SPECS]
        urls = ["http://localhost:8000/health"] + [
            f"http://localhost:{s['port']}{s['rpc_path'].rstrip('/')}/.well-known/agent-card.json"
            for s in AGENT_SPECS
        ]
        results = await asyncio.gather(*(client.get(u) for u in urls), return_exceptions=True)
        for port, res in zip(ports, results):
            if not isinstance(res, Exception) and getattr(res, "status_code", 500) < 400:
                live_ports.add(port)
    docker_up = bool(live_ports - {8000})
    return docker_up, live_ports


async def _load_agent_mesh_metadata(mode: str = "dev") -> Tuple[List[Dict[str, Any]], bool]:
    mesh: List[Dict[str, Any]] = []
    loc = _DEV_ENV.get("VERTEX_ENGINE_LOCATION", "us-central1")
    docker_up, live_ports = await _check_local_docker_Status() if mode == "local" else (False, set())

    for spec in AGENT_SPECS:
        dev_file = ROOT_DIR / spec["dir"] / ".env.dev"
        vals = dotenv_values(dev_file) if dev_file.exists() else {}
        resource_name = vals.get("AGENT_ENGINE_RESOURCE_NAME", "")
        engine_id = resource_name.rsplit("/", 1)[-1] if resource_name else ""
        cloud_rpc_url = (
            f"https://{loc}-aiplatform.googleapis.com/reasoningEngines/v1/{resource_name}/api{spec['rpc_path']}"
            if resource_name
            else ""
        )
        local_rpc_url = f"http://localhost:{spec['port']}{spec['rpc_path']}"
        mesh.append(
            {
                **spec,
                "resource_name": resource_name,
                "engine_id": engine_id,
                "cloud_rpc_url": cloud_rpc_url,
                "local_rpc_url": local_rpc_url,
                "deployed": bool(engine_id),
                "docker_live": spec["port"] in live_ports,
            }
        )
    return mesh, docker_up


app = FastAPI(title="AURA // VOYAGE — Polyglot A2UI Travel Concierge Studio")

_RUNNERS: Dict[str, Any] = {}
_SESSIONS: Dict[str, str] = {}


def _infer_downstream_agents(text: str, active_agents: List[str]) -> None:
    lower_all = text.lower()
    if "save my traveler profile" in lower_all or ("home airport is sfo" in lower_all and "vegetarian" in lower_all):
        return
    has_mid = any(
        m in active_agents
        for m in ("inspiration_agent", "planning_agent", "booking_agent", "pre_trip_agent", "in_trip_agent", "post_trip_agent")
    )
    if has_mid:
        if "inspiration_agent" in active_agents:
            for a in ("place_agent", "poi_agent"):
                if a not in active_agents:
                    active_agents.append(a)
        if "planning_agent" in active_agents:
            if any(k in lower_all for k in ("hotel", "monasterio", "suite", "itinerary")):
                sub = ("flight_seat_selection_agent", "hotel_search_agent", "hotel_room_selection_agent", "itinerary_agent") if "seat" in lower_all else ("hotel_search_agent", "hotel_room_selection_agent", "itinerary_agent")
            else:
                sub = ("flight_search_agent", "flight_seat_selection_agent")
            for a in sub:
                if a not in active_agents:
                    active_agents.append(a)
        if "in_trip_agent" in active_agents:
            for a in ("day_of_agent", "trip_monitor_agent"):
                if a not in active_agents:
                    active_agents.append(a)
        return

    rules = [
        (("inspire", "points of interest", "destination ideas", "inspiration_agent"), ("inspiration_agent", "place_agent", "poi_agent")),
        (("search for flights", "pick a window seat", "flight_search_agent", "flight_seat_selection_agent"), ("planning_agent", "flight_search_agent", "flight_seat_selection_agent")),
        (("monasterio", "palacio del inka", "deluxe andean suite", "hotel_search_agent", "itinerary_agent"), ("planning_agent", "hotel_search_agent", "hotel_room_selection_agent", "itinerary_agent")),
        (("apple pay", "google pay", "reservation", "payment", "booking_agent"), ("booking_agent",)),
        (("visa", "packing", "acetazolamide", "diamox", "pre_trip_agent"), ("pre_trip_agent",)),
        (("we have arrived", "velasco astete", "on time", "in_trip_agent"), ("in_trip_agent", "day_of_agent", "trip_monitor_agent")),
        (("trip was unforgettable", "for future trips", "post_trip_agent"), ("post_trip_agent",)),
    ]
    for keywords, agents in rules:
        if any(k in lower_all for k in keywords):
            for a in agents:
                if a not in active_agents:
                    active_agents.append(a)


async def _get_or_create_runner(mode: str):
    """Initialize ADK Runner for root_agent in either 'local' (.env) or 'dev' (.env.dev) mode."""
    if mode in _RUNNERS:
        return _RUNNERS[mode]

    env_src = _DEV_ENV if (mode == "dev" and _DEV_ENV) else _LOCAL_ENV
    for k, v in env_src.items():
        if v is not None:
            os.environ[k] = v
    is_dev = mode == "dev" and bool(_DEV_ENV)
    os.environ["LOCAL_MODE"] = "false" if is_dev else "true"
    os.environ["OTEL_TO_CLOUD"] = "true" if is_dev else "false"
    os.environ["BQ_ANALYTICS_ENABLED"] = "true" if is_dev else "false"

    from google.adk.models.google_llm import Gemini
    from google.genai import types
    from root_concierge_agent.runner import create_runner

    runner = await create_runner()
    model_name = os.environ.get("GENAI_MODEL", "gemini-3-flash-preview")
    runner.agent.model = Gemini(
        model=model_name,
        retry_options=types.HttpRetryOptions(
            attempts=5,
            initial_delay=2.0,
            max_delay=30.0,
            exp_base=2.0,
            http_status_codes=[429, 500, 502, 503, 504],
        ),
    )
    _RUNNERS[mode] = runner
    return runner


def _normalize_agent_id(raw_name: str) -> str:
    short = str(raw_name or "").strip().rsplit("/", 1)[-1]
    short = short.replace("-", "_").removesuffix("_a2a")
    if short == "root_concierge_agent":
        return "root_agent"
    return short or "sub_agent"


async def _call_a2a_jsonrpc(
    rpc_url: str,
    agent_spec: Dict[str, Any],
    message: str,
    user_id: str,
    context_id: str,
    use_cloud_auth: bool,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Send a standard A2A 1.0 JSON-RPC SendMessage request with automatic 429 retry backoff and full history trace extraction."""
    headers = {"Content-Type": "application/json", "A2A-Version": "1.0", "x-user-id": user_id}
    if use_cloud_auth:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        headers["Authorization"] = f"Bearer {creds.token}"

    t0 = time.monotonic()
    reply = ""
    result: Dict[str, Any] = {}
    sent_msg_id = ""
    for attempt in range(4):
        sent_msg_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": sent_msg_id,
                    "contextId": context_id,
                    "role": "ROLE_USER",
                    "parts": [{"text": message}],
                }
            },
        }
        try:
            async with httpx.AsyncClient(timeout=240.0) as client:
                resp = await client.post(rpc_url, json=payload, headers=headers)
                if resp.status_code == 429 and attempt < 3:
                    await asyncio.sleep(2.0 * (2 ** attempt))
                    continue
                resp.raise_for_status()
                raw_res = resp.json().get("result", {})
                result = raw_res.get("task") or raw_res.get("message") or raw_res
        except Exception as exc:
            if ("429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)) and attempt < 3:
                await asyncio.sleep(2.0 * (2 ** attempt))
                continue
            raise

        history = result.get("history", [])
        start_idx = 0
        for idx, h_item in enumerate(history):
            if h_item.get("messageId") == sent_msg_id or h_item.get("role") in ("user", "ROLE_USER"):
                start_idx = idx
        turn_history = history[start_idx:] if history else []

        primary_groups = [
            result.get("parts", []),
            result.get("status", {}).get("message", {}).get("parts", []),
            *(art.get("parts", []) for art in result.get("artifacts", [])),
        ]
        texts = [p["text"] for group in primary_groups for p in group if p.get("text", "").strip()]
        if not texts:
            texts = [
                p["text"]
                for h in turn_history
                if h.get("role") in ("agent", "ROLE_AGENT")
                for p in h.get("parts", [])
                if p.get("text", "").strip()
            ]
        reply = "\n\n".join(dict.fromkeys(texts)) or json.dumps(result, indent=2)
        if ("429" in reply and "RESOURCE_EXHAUSTED" in reply) and attempt < 3:
            await asyncio.sleep(2.5 * (2 ** attempt))
            continue
        break

    latency_ms = int((time.monotonic() - t0) * 1000)
    trace_events: List[Dict[str, Any]] = [
        {
            "kind": "A2A_JSONRPC_CALL",
            "from_actor": f"traveler ({user_id})",
            "to_actor": agent_spec["name"],
            "agent": agent_spec["name"],
            "framework": agent_spec["framework"],
            "detail": f"POST {rpc_url} ({latency_ms} ms)",
            "message": message,
            "latency_ms": latency_ms,
        }
    ]

    call_id_to_target: Dict[str, str] = {}
    for h_item in turn_history:
        for part in h_item.get("parts", []):
            d = part.get("data") if isinstance(part.get("data"), dict) else None
            if d is not None:
                tool_name = str(d.get("name") or "tool")
                call_id = str(d.get("id") or "")
                if "args" in d and isinstance(d["args"], dict):
                    args_dict = d["args"]
                    if tool_name == "call_agent":
                        target_ag = _normalize_agent_id(args_dict.get("agent_name", ""))
                        if call_id:
                            call_id_to_target[call_id] = target_ag
                        trace_events.append(
                            {
                                "kind": "A2A_AGENT_MESSAGE",
                                "direction": "request",
                                "from_actor": agent_spec["name"],
                                "to_actor": target_ag,
                                "tool": "call_agent",
                                "args": args_dict,
                                "message": str(args_dict.get("message", "")),
                            }
                        )
                    else:
                        trace_events.append(
                            {
                                "kind": "TOOL_CALL",
                                "from_actor": agent_spec["name"],
                                "to_actor": tool_name,
                                "tool": tool_name,
                                "args": args_dict,
                            }
                        )
                elif "response" in d:
                    resp_obj = d["response"]
                    if tool_name == "call_agent":
                        target_ag = call_id_to_target.get(call_id, "sub_agent")
                        resp_msg = (
                            resp_obj.get("result")
                            if isinstance(resp_obj, dict) and "result" in resp_obj
                            else (resp_obj if isinstance(resp_obj, str) else json.dumps(resp_obj, ensure_ascii=False))
                        )
                        trace_events.append(
                            {
                                "kind": "A2A_AGENT_MESSAGE",
                                "direction": "response",
                                "from_actor": target_ag,
                                "to_actor": agent_spec["name"],
                                "tool": "call_agent",
                                "message": str(resp_msg),
                            }
                        )
                    else:
                        trace_events.append(
                            {
                                "kind": "TOOL_RESULT",
                                "from_actor": tool_name,
                                "to_actor": agent_spec["name"],
                                "tool": tool_name,
                                "response": resp_obj,
                            }
                        )

    trace_events.append(
        {
            "kind": "A2A_FINAL_REPLY",
            "from_actor": agent_spec["name"],
            "to_actor": f"traveler ({user_id})",
            "message": reply,
            "latency_ms": latency_ms,
        }
    )
    return reply, trace_events


@app.get("/api/mesh")
async def get_mesh_status(mode: str = DEFAULT_ENV_MODE):
    mesh, docker_up = await _load_agent_mesh_metadata(mode=mode)
    return JSONResponse(
        {
            "default_mode": DEFAULT_ENV_MODE,
            "active_mode": mode,
            "docker_up": docker_up,
            "project_id": _DEV_ENV.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
            "location": _DEV_ENV.get("VERTEX_ENGINE_LOCATION", "us-central1"),
            "model": _DEV_ENV.get("GENAI_MODEL", "gemini-3-flash-preview"),
            "session_engine_id": _DEV_ENV.get("SESSION_AGENT_ENGINE_ID", "") if mode == "dev" else "InMemorySessionService",
            "memory_engine_id": _DEV_ENV.get("MEMORY_AGENT_ENGINE_ID", "") if mode == "dev" else "SharedInMemoryMemoryService",
            "registry_label": "Google Cloud Agent Registry" if mode == "dev" else ("Local Docker Agent Registry (:8000)" if docker_up else "Local Agent Registry Catalog"),
            "agents": mesh,
        }
    )


def _sanitize_session_id(raw_id: str) -> str:
    """Normalize session_id to satisfy both ADK and Vertex AI SessionService rules:
    lowercase letters, digits, and hyphens only, starting and ending with alphanumeric.
    """
    cleaned = re.sub(r"[^a-z0-9-]+", "-", (raw_id or "").lower()).strip("-")
    if not cleaned:
        return f"session-{uuid.uuid4().hex[:6]}"
    return cleaned[:63]


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    body = await request.json()
    message: str = (body.get("message") or "").strip()
    mode: str = body.get("mode", DEFAULT_ENV_MODE)
    target_agent: str = body.get("target_agent", "root_agent")
    user_id: str = (body.get("user_id") or DEFAULT_TRAVELER).strip() or DEFAULT_TRAVELER
    raw_session_key: str = body.get("session_id") or f"{mode}-{user_id}"
    session_key: str = _sanitize_session_id(raw_session_key)

    if not message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    t0 = time.monotonic()
    ag_ui_events: List[Dict[str, Any]] = []
    active_agents: List[str] = [target_agent]
    spec = next((s for s in AGENT_SPECS if s["name"] == target_agent), AGENT_SPECS[0])

    try:
        docker_up, _ = await _check_local_docker_Status() if mode == "local" else (False, set())
        dev_file = ROOT_DIR / spec["dir"] / ".env.dev"
        res_name = (dotenv_values(dev_file) if dev_file.exists() else {}).get("AGENT_ENGINE_RESOURCE_NAME", "")

        if (mode == "dev" and res_name) or (mode == "local" and docker_up):
            if mode == "dev":
                loc = _DEV_ENV.get("VERTEX_ENGINE_LOCATION", "us-central1")
                rpc_url = f"https://{loc}-aiplatform.googleapis.com/reasoningEngines/v1/{res_name}/api{spec['rpc_path']}"
            else:
                rpc_url = f"http://localhost:{spec['port']}{spec['rpc_path']}"
                if target_agent == "root_agent":
                    ag_ui_events.append(
                        {
                            "kind": "LOCAL_DOCKER_REGISTRY",
                            "detail": "Using tc-local-agent-registry (http://localhost:8000/v1) + 16 Docker A2A containers (:8001–:8016)",
                        }
                    )
            reply_text, direct_events = await _call_a2a_jsonrpc(
                rpc_url, spec, message, user_id=user_id, context_id=session_key, use_cloud_auth=(mode == "dev")
            )
            ag_ui_events.extend(direct_events)
            for ev in direct_events:
                if ev.get("kind") == "A2A_AGENT_MESSAGE":
                    for actor_key in ("from_actor", "to_actor"):
                        actor_id = ev.get(actor_key, "")
                        if actor_id and actor_id not in active_agents and any(s["name"] == actor_id for s in AGENT_SPECS):
                            active_agents.append(actor_id)
                    
            if target_agent == "root_agent":
                _infer_downstream_agents(message, active_agents)
        else:
            runner = await _get_or_create_runner(mode)
            from google.genai import types
            from root_concierge_agent.auth import current_user_id

            current_user_id.set(user_id)
            if session_key not in _SESSIONS:
                session = await runner.session_service.create_session(app_name=runner.app_name, user_id=user_id)
                _SESSIONS[session_key] = session.id
            adk_session_id = _SESSIONS[session_key]

            content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
            replies: List[str] = []

            for attempt in range(4):
                try:
                    replies.clear()
                    last_called_target = "sub_agent"
                    async for event in runner.run_async(user_id=user_id, session_id=adk_session_id, new_message=content):
                        for part in (event.content.parts if event.content and event.content.parts else []):
                            fc = getattr(part, "function_call", None)
                            if fc:
                                args_dict = dict(fc.args) if getattr(fc, "args", None) else {}
                                if fc.name == "call_agent":
                                    last_called_target = _normalize_agent_id(args_dict.get("agent_name", ""))
                                    if last_called_target not in active_agents:
                                        active_agents.append(last_called_target)
                                    ag_ui_events.append(
                                        {
                                            "kind": "A2A_AGENT_MESSAGE",
                                            "direction": "request",
                                            "from_actor": target_agent,
                                            "to_actor": last_called_target,
                                            "tool": "call_agent",
                                            "args": args_dict,
                                            "message": str(args_dict.get("message", "")),
                                        }
                                    )
                                else:
                                    ag_ui_events.append(
                                        {
                                            "kind": "TOOL_CALL",
                                            "from_actor": target_agent,
                                            "to_actor": fc.name,
                                            "tool": fc.name,
                                            "args": args_dict,
                                        }
                                    )
                                _infer_downstream_agents(json.dumps(args_dict), active_agents)
                            fr = getattr(part, "function_response", None)
                            if fr:
                                resp_dict = dict(fr.response) if getattr(fr, "response", None) else {}
                                if fr.name == "call_agent":
                                    resp_msg = resp_dict.get("result") or json.dumps(resp_dict, ensure_ascii=False)
                                    ag_ui_events.append(
                                        {
                                            "kind": "A2A_AGENT_MESSAGE",
                                            "direction": "response",
                                            "from_actor": last_called_target,
                                            "to_actor": target_agent,
                                            "tool": "call_agent",
                                            "message": str(resp_msg),
                                        }
                                    )
                                else:
                                    ag_ui_events.append(
                                        {
                                            "kind": "TOOL_RESULT",
                                            "from_actor": fr.name,
                                            "to_actor": target_agent,
                                            "tool": fr.name,
                                            "response": resp_dict,
                                        }
                                    )
                            if getattr(part, "text", None):
                                replies.append(part.text)
                    break
                except Exception as run_exc:
                    if ("429" in str(run_exc) or "RESOURCE_EXHAUSTED" in str(run_exc)) and attempt < 3:
                        await asyncio.sleep(2.5 * (2 ** attempt))
                        continue
                    raise

            reply_text = "\n".join(replies).strip() or "(No text returned)"
            _infer_downstream_agents(reply_text, active_agents)

        total_ms = int((time.monotonic() - t0) * 1000)

        return JSONResponse(
            {
                "reply": reply_text,
                "active_agents": active_agents,
                "ag_ui_events": ag_ui_events,
                "latency_ms": total_ms,
                "mode": mode,
                "session_id": session_key,
            }
        )
    except Exception as exc:
        return JSONResponse(
            {
                "error": str(exc),
                "active_agents": active_agents,
                "ag_ui_events": ag_ui_events,
            },
            status_code=500,
        )


@app.post("/api/new-session")
async def new_session_endpoint(request: Request):
    body = await request.json()
    user_id = (body.get("user_id") or DEFAULT_TRAVELER).strip() or DEFAULT_TRAVELER
    mode = body.get("mode", DEFAULT_ENV_MODE)
    new_key = _sanitize_session_id(f"{mode}-{user_id}-{uuid.uuid4().hex[:6]}")
    return JSONResponse({"session_id": new_key, "user_id": user_id})


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AURA // VOYAGE — Polyglot A2UI & AG-UI Travel Concierge Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    body {
      font-family: 'Plus Jakarta Sans', sans-serif;
      background: radial-gradient(circle at 15% 10%, rgba(16, 185, 129, 0.10), transparent 35%),
                  radial-gradient(circle at 85% 15%, rgba(99, 102, 241, 0.12), transparent 40%),
                  radial-gradient(circle at 50% 90%, rgba(245, 158, 11, 0.08), transparent 40%),
                  #07090e;
      color: #f1f5f9;
    }
    .mono { font-family: 'JetBrains Mono', monospace; }
    .glass {
      background: rgba(15, 23, 42, 0.72);
      backdrop-filter: blur(16px);
      border: 1px solid rgba(148, 163, 184, 0.14);
    }
    .glass-card {
      background: linear-gradient(145deg, rgba(30, 41, 59, 0.65), rgba(15, 23, 42, 0.85));
      border: 1px solid rgba(148, 163, 184, 0.16);
    }
    .agent-node {
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .agent-node.active-pulse {
      transform: translateY(-2px) scale(1.02);
      box-shadow: 0 0 22px rgba(16, 185, 129, 0.45), inset 0 0 12px rgba(16, 185, 129, 0.2);
      border-color: #10b981 !important;
    }
    .agent-node.active-pulse-langgraph {
      transform: translateY(-2px) scale(1.02);
      box-shadow: 0 0 22px rgba(245, 158, 11, 0.5), inset 0 0 12px rgba(245, 158, 11, 0.25);
      border-color: #f59e0b !important;
    }
    .agent-node.active-pulse-crewai {
      transform: translateY(-2px) scale(1.02);
      box-shadow: 0 0 22px rgba(217, 70, 239, 0.5), inset 0 0 12px rgba(217, 70, 239, 0.25);
      border-color: #d946ef !important;
    }
    .prose p { margin-bottom: 0.6rem; line-height: 1.6; }
    .prose ul, .prose ol { margin-left: 1.25rem; margin-bottom: 0.6rem; list-style: disc; }
    .prose li { margin-bottom: 0.25rem; }
    .prose strong { color: #38bdf8; font-weight: 600; }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.25); border-radius: 9999px; }
  </style>
</head>
<body class="h-screen flex flex-col overflow-hidden select-none">

  <!-- TOP HEADER BAR -->
  <header class="glass px-6 py-3 flex items-center justify-between border-b border-slate-800/80 z-20">
    <div class="flex items-center gap-4">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 via-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-emerald-500/20 font-extrabold text-slate-950 text-lg">
        AV
      </div>
      <div>
        <div class="flex items-center gap-2.5">
          <h1 class="text-lg font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-100 to-emerald-300 bg-clip-text text-transparent">
            AURA // VOYAGE
          </h1>
          <span class="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
            A2UI + AG-UI Studio
          </span>
          <span class="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 mono" id="model-badge">
            gemini-3-flash-preview (global)
          </span>
        </div>
        <p class="text-xs text-slate-400" id="env-subtitle">
          16 Polyglot A2A Agents • Google ADK (14) + LangGraph (1) + CrewAI (1)
        </p>
      </div>
    </div>

    <!-- ENVIRONMENT SWITCHER: LOCAL DOCKER (.env) vs DEV GCP AGENT RUNTIME (.env.dev) -->
    <div class="flex items-center gap-3">
      <div class="flex items-center bg-slate-900/95 p-1 rounded-xl border border-slate-800 text-xs">
        <button id="mode-dev" onclick="setMode('dev')" class="px-3.5 py-1.5 rounded-lg font-semibold transition bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
          ☁️ Dev (GCP Agent Runtime • .env.dev)
        </button>
        <button id="mode-local" onclick="setMode('local')" class="px-3.5 py-1.5 rounded-lg font-semibold transition text-slate-400 hover:text-slate-200">
          🐳 Local (Docker Setup • .env)
        </button>
      </div>

      <div class="flex items-center gap-1.5 bg-slate-900/90 px-3 py-1.5 rounded-xl border border-slate-800 hover:border-emerald-500/40 text-xs transition" title="Customize traveler name / user_id (propagated via x-user-id across all 16 agents, Session & Memory Bank)">
        <span class="text-slate-400">👤 Traveler:</span>
        <input id="user-id-input" value="__DEFAULT_TRAVELER__" placeholder="sohil" onchange="onTravelerChange()" class="bg-transparent text-emerald-300 font-semibold mono w-32 focus:outline-none focus:text-white" />
      </div>

      <button onclick="startNewSession()" class="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 border border-slate-700 transition flex items-center gap-1.5" title="Start a fresh session">
        🔄 New Session
      </button>
    </div>
  </header>

  <!-- ONE-CLICK DEMO STORYLINE BAR (ALL 9 FLOWS) -->
  <div class="bg-slate-950/90 border-b border-slate-800/80 px-6 py-2.5 flex items-center gap-2 overflow-x-auto">
    <span class="text-[11px] font-bold uppercase tracking-wider text-slate-400 shrink-0 mr-1">
      🎬 Live Demo Acts:
    </span>
    <button onclick="runDemoAct(1)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-cyan-950/60 border border-cyan-500/30 hover:border-cyan-400 text-xs text-cyan-200 transition">
      1️⃣ Save Traveler Profile <span class="text-[10px] text-cyan-400 font-bold ml-1">(Memory)</span>
    </button>
    <button onclick="runDemoAct(2)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-emerald-950/60 border border-slate-800 hover:border-emerald-500/40 text-xs text-slate-200 transition">
      2️⃣ Inspire & POIs <span class="text-[10px] text-emerald-400 ml-1">(ADK)</span>
    </button>
    <button onclick="runDemoAct(3)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-emerald-950/60 border border-slate-800 hover:border-emerald-500/40 text-xs text-slate-200 transition">
      3️⃣ Flights & Seats <span class="text-[10px] text-emerald-400 ml-1">(ADK)</span>
    </button>
    <button onclick="runDemoAct(4)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-emerald-950/60 border border-slate-800 hover:border-emerald-500/40 text-xs text-slate-200 transition">
      4️⃣ Hotels & 4-Day Itinerary <span class="text-[10px] text-emerald-400 ml-1">(ADK)</span>
    </button>
    <button onclick="runDemoAct(5)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-amber-950/60 border border-amber-500/30 hover:border-amber-400 text-xs text-amber-200 transition">
      5️⃣ Book w/ Apple Pay <span class="text-[10px] text-amber-400 font-bold ml-1">(LangGraph)</span>
    </button>
    <button onclick="runDemoAct(6)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-amber-950/60 border border-amber-500/30 hover:border-amber-400 text-xs text-amber-200 transition">
      6️⃣ Retry w/ Google Pay <span class="text-[10px] text-amber-400 font-bold ml-1">(LangGraph)</span>
    </button>
    <button onclick="runDemoAct(7)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-fuchsia-950/60 border border-fuchsia-500/30 hover:border-fuchsia-400 text-xs text-fuchsia-200 transition">
      7️⃣ Pre-Trip & Packing <span class="text-[10px] text-fuchsia-400 font-bold ml-1">(CrewAI)</span>
    </button>
    <button onclick="runDemoAct(8)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-emerald-950/60 border border-slate-800 hover:border-emerald-500/40 text-xs text-slate-200 transition">
      8️⃣ In-Trip Transit & Monitor <span class="text-[10px] text-emerald-400 ml-1">(ADK)</span>
    </button>
    <button onclick="runDemoAct(9)" class="shrink-0 px-3 py-1 rounded-lg bg-slate-900 hover:bg-cyan-950/60 border border-cyan-500/30 hover:border-cyan-400 text-xs text-cyan-200 transition">
      9️⃣ Post-Trip + Memory Bank <span class="text-[10px] text-cyan-400 font-bold ml-1">(Memory)</span>
    </button>
  </div>

  <!-- MAIN WORKSPACE -->
  <div class="flex-1 grid grid-cols-12 overflow-hidden">

    <!-- LEFT/CENTER (7 COLS): A2UI CONVERSATION & GENERATIVE WIDGET STREAM -->
    <div class="col-span-7 flex flex-col border-r border-slate-800/80 overflow-hidden select-text">
      <div id="chat-stream" class="flex-1 overflow-y-auto p-6 space-y-5">
        <div class="glass-card rounded-2xl p-5 border border-emerald-500/20">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-bold uppercase tracking-wider text-emerald-400">
              ✨ AURA // VOYAGE — Dual-Environment Polyglot Concierge
            </span>
            <span class="text-[11px] text-slate-400 mono" id="session-indicator">Session: active</span>
          </div>
          <p class="text-sm text-slate-200 leading-relaxed">
            Switch seamlessly in the top bar between:
            <br/>• <strong>☁️ Dev (GCP Agent Runtime • .env.dev)</strong> — Invokes your 16 deployed BYOC A2A containers in Vertex AI Agent Engine via Google Cloud Agent Registry, backed by shared Vertex AI Session & Memory Bank engines, Cloud Trace, and BigQuery Looker Analytics.
            <br/>• <strong>🐳 Local (Docker Setup • .env)</strong> — Invokes your local Docker Compose A2A mesh (<code>:8000</code> local registry + <code>:8001–:8016</code> containers) with fast in-memory state.
          </p>
        </div>
      </div>

      <!-- PROMPT COMPOSER -->
      <div class="p-4 glass border-t border-slate-800/80">
        <form onsubmit="submitPrompt(event)" class="flex items-center gap-3">
          <select id="target-agent-select" class="bg-slate-900 border border-slate-700 rounded-xl px-3 py-3 text-xs font-semibold text-slate-200 focus:outline-none focus:border-emerald-500">
            <option value="root_agent">🎯 root_agent (Full Mesh Orchestrator)</option>
            <option value="inspiration_agent">🌍 inspiration_agent (ADK)</option>
            <option value="planning_agent">✈️ planning_agent (ADK)</option>
            <option value="booking_agent">💳 booking_agent (LangGraph)</option>
            <option value="pre_trip_agent">🛂 pre_trip_agent (CrewAI)</option>
            <option value="in_trip_agent">🚕 in_trip_agent (ADK)</option>
            <option value="post_trip_agent">🧠 post_trip_agent (ADK)</option>
            <option value="place_agent">🏔️ place_agent (ADK)</option>
            <option value="poi_agent">📍 poi_agent (ADK)</option>
            <option value="flight_search_agent">🛫 flight_search_agent (ADK)</option>
            <option value="flight_seat_selection_agent">💺 flight_seat_selection_agent (ADK)</option>
            <option value="hotel_search_agent">🏨 hotel_search_agent (ADK)</option>
            <option value="hotel_room_selection_agent">🛏️ hotel_room_selection_agent (ADK)</option>
            <option value="itinerary_agent">🗓️ itinerary_agent (ADK)</option>
            <option value="day_of_agent">🚗 day_of_agent (ADK)</option>
            <option value="trip_monitor_agent">📡 trip_monitor_agent (ADK)</option>
          </select>
          <input
            id="prompt-input"
            type="text"
            placeholder="Ask AURA // VOYAGE to inspire, plan flights & hotels, book via LangGraph, or run CrewAI pre-trip checks..."
            class="flex-1 bg-slate-900/90 border border-slate-700/80 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-400"
          />
          <button
            id="send-btn"
            type="submit"
            class="px-5 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-slate-950 font-bold text-sm shadow-lg shadow-emerald-500/20 transition"
          >
            Send ↗
          </button>
        </form>
      </div>
    </div>

    <!-- RIGHT (5 COLS): LIVE 16-AGENT MESH TOPOLOGY & AG-UI TELEMETRY STREAM -->
    <div class="col-span-5 flex flex-col bg-slate-950/60 overflow-hidden">
      <div class="p-4 border-b border-slate-800/80 flex items-center justify-between">
        <div>
          <h2 class="text-xs font-extrabold uppercase tracking-wider text-slate-200 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
            <span id="mesh-header-title">Live 16-Agent A2A Mesh (Dev GCP Runtime)</span>
          </h2>
          <p class="text-[11px] text-slate-400 mono mt-0.5" id="shared-engines-label">
            Loading environment metadata...
          </p>
        </div>
        <div id="gcp-console-links" class="flex items-center gap-1.5 text-[11px]">
          <a id="link-trace" href="#" target="_blank" class="px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 text-sky-400 border border-slate-800">Cloud Trace ↗</a>
          <a id="link-registry" href="#" target="_blank" class="px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 text-emerald-400 border border-slate-800">Agent Registry ↗</a>
          <a id="link-engine" href="#" target="_blank" class="px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 text-purple-400 border border-slate-800">Agent Engine ↗</a>
          <a id="link-bq" href="#" target="_blank" class="px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 text-amber-400 border border-slate-800">BigQuery ↗</a>
        </div>
      </div>

      <!-- 16-AGENT INTERACTIVE MESH GRID -->
      <div class="p-4 overflow-y-auto space-y-3 flex-1" id="mesh-container"></div>

      <!-- AG-UI TELEMETRY & A2A DISCOVERY EVENT DRAWER -->
      <div class="h-72 border-t border-slate-800/90 bg-slate-950/95 flex flex-col">
        <div class="px-4 py-2 border-b border-slate-800/80 flex items-center justify-between">
          <span class="text-[11px] font-bold uppercase tracking-wider text-slate-400">
            📡 AG-UI / Agent Registry / A2A Message & Tool Stream
          </span>
          <div class="flex items-center gap-2">
            <span id="latency-badge" class="text-[11px] mono text-emerald-400">Ready</span>
            <button onclick="document.getElementById('telemetry-log').innerHTML=''" class="px-2 py-0.5 rounded bg-slate-900 hover:bg-slate-800 text-[10px] text-slate-400 border border-slate-800">Clear</button>
          </div>
        </div>
        <div id="telemetry-log" class="flex-1 overflow-y-auto p-3 space-y-2 text-xs mono text-slate-300 select-text">
          <div class="text-slate-500">Waiting for agent invocation...</div>
        </div>
      </div>
    </div>

  </div>

  <script>
    let currentMode = '__DEFAULT_MODE__';
    let currentSessionId = '';
    let meshAgents = [];

    const STORY_STATE = {
      outboundFlight: '',
      returnFlight: '',
      seat: '',
      hotel: 'Belmond Hotel Monasterio'
    };

    function getDemoPrompt(actNumber) {
      const flightDesc = STORY_STATE.outboundFlight
        ? (STORY_STATE.returnFlight
            ? `flight ${STORY_STATE.outboundFlight} (and return ${STORY_STATE.returnFlight})`
            : `flight ${STORY_STATE.outboundFlight}`)
        : 'your recommended LATAM flight';
      const seatDesc = STORY_STATE.seat ? `window seat ${STORY_STATE.seat}` : 'your recommended window seat';
      const hotelDesc = STORY_STATE.hotel || 'Belmond Hotel Monasterio';

      const prompts = {
        1: "Hi! Before we plan a trip, please save my traveler profile in memory: my home airport is SFO, I am vegetarian, I prefer window seats on flights, and I love boutique luxury hotels with mountain or cultural views.",
        2: "We want to plan an unforgettable 4-day South American adventure in May with ancient ruins, dramatic mountain scenery, and vibrant local culture. Can you inspire us with destination ideas and top points of interest?",
        3: "Cusco, the Sacred Valley, and Machu Picchu sound incredible! Let's plan a 4-day trip to Cusco departing from San Francisco (SFO) to Cusco (CUZ) from May 10, 2027 to May 14, 2027 for 1 traveler. Please search for flights and help me pick a window seat.",
        4: `Let's select ${flightDesc} with ${seatDesc}! Now please search for boutique luxury hotels in Cusco for May 10 to May 14, 2027, select a luxury suite at ${hotelDesc}, and generate the complete 4-day Cusco & Machu Picchu itinerary.`,
        5: `The 4-day Cusco & Machu Picchu itinerary looks perfect! Please go ahead and create the reservations for our selected ${flightDesc} and ${hotelDesc}, show me the payment options, and try paying with Apple Pay first.`,
        6: "Since Apple Pay was declined, please process the payment for both reservations using Google Pay instead.",
        7: "Now that our flights and hotel are booked and paid for, what do I need to prepare before our trip to Cusco and Machu Picchu in May? Please check visa requirements for US citizens, medical/vaccine and altitude advice, weather/storm advisories, and a packing checklist.",
        8: `We have arrived in Cusco! Can you check the status of our flights and tell me the best transit route and travel time from Alejandro Velasco Astete Airport (CUZ) to ${hotelDesc} in the Historic Center?`,
        9: "Our Peru trip was unforgettable! For future trips, please save my preferences to Memory Bank: I always prefer window seats on flights, boutique historic luxury hotels with oxygen-enriched rooms at high altitude, and private early-morning archaeological tours. Then confirm what preferences you have stored for me."
      };
      return prompts[actNumber] || '';
    }

    function syncStoryFromReply(replyText) {
      if (!replyText) return;
      const recPart = replyText.includes('Recommendation')
        ? replyText.split('Recommendation').slice(-1)[0]
        : replyText;

      const recFlights = [...new Set((recPart.match(/\b(?:LA|CM|AV|AA|UA|DL)\d{3,4}\b/g) || []))];
      const allFlights = [...new Set((replyText.match(/\b(?:LA|CM|AV|AA|UA|DL)\d{3,4}\b/g) || []))];
      const flights = recFlights.length ? recFlights : allFlights;
      if (flights.length >= 1) STORY_STATE.outboundFlight = flights[0];
      if (flights.length >= 2) STORY_STATE.returnFlight = flights[1];

      const recSeats = [...new Set((recPart.match(/\b\d{1,2}[AF]\b/g) || recPart.match(/\b\d{1,2}[A-K]\b/g) || []))];
      if (recSeats.length >= 1) STORY_STATE.seat = recSeats[0];

      const hotels = ['Belmond Hotel Monasterio', 'Palacio del Inka', 'Inkaterra La Casona', 'JW Marriott El Convento Cusco'];
      for (const h of hotels) {
        if (recPart.toLowerCase().includes(h.toLowerCase())) {
          STORY_STATE.hotel = h;
          break;
        }
      }
    }

    let dockerUp = false;

    async function loadMesh() {
      const res = await fetch(`/api/mesh?mode=${currentMode}`);
      const data = await res.json();
      meshAgents = data.agents || [];
      dockerUp = Boolean(data.docker_up);
      document.getElementById('model-badge').textContent = `${data.model} (global)`;
      document.getElementById('mesh-header-title').textContent =
        currentMode === 'dev'
          ? 'Live Registered A2A Services (Dev • GCP Agent Runtime)'
          : `Live Registered A2A Services (Local • ${dockerUp ? 'Docker :8000–:8016 UP' : 'In-Memory'})`;
      document.getElementById('shared-engines-label').textContent =
        `${data.registry_label} • Session: ${data.session_engine_id} • Memory: ${data.memory_engine_id}`;
      const gcpLinks = document.getElementById('gcp-console-links');
      if (gcpLinks) {
        gcpLinks.style.display = currentMode === 'dev' ? 'flex' : 'none';
      }
      if (data.project_id && currentMode === 'dev') {
        document.getElementById('link-trace').href = `https://console.cloud.google.com/traces/list?project=${data.project_id}`;
        document.getElementById('link-registry').href = `https://console.cloud.google.com/agent-platform/agent-registry?project=${data.project_id}`;
        document.getElementById('link-engine').href = `https://console.cloud.google.com/vertex-ai/agents/agent-engines?project=${data.project_id}`;
        document.getElementById('link-bq').href = `https://console.cloud.google.com/bigquery?project=${data.project_id}`;
      }
      renderMesh([]);
    }

    function renderMesh(activeNames) {
      const container = document.getElementById('mesh-container');
      const activeSet = new Set(activeNames);
      const liveServices = meshAgents.filter(a =>
        currentMode === 'dev' ? a.deployed : (dockerUp ? a.docker_live : true)
      );

      if (!liveServices.length) {
        container.innerHTML = `<div class="p-4 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-400">No live services detected in ${currentMode.toUpperCase()} mode.</div>`;
        return;
      }

      container.innerHTML = `
        <div>
          <div class="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
            <span>📡 Agent Registry Services (Dynamic A2A Routing)</span>
            <span class="text-emerald-400 mono">${liveServices.length} LIVE</span>
          </div>
          <div class="grid grid-cols-2 gap-2">
            ${liveServices.map(a => {
              const isActive = activeSet.has(a.name);
              let pulseClass = '';
              let badgeClass = 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
              if (a.framework === 'LangGraph') {
                badgeClass = 'bg-amber-500/15 text-amber-300 border-amber-500/30';
                if (isActive) pulseClass = 'active-pulse-langgraph';
              } else if (a.framework === 'CrewAI') {
                badgeClass = 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30';
                if (isActive) pulseClass = 'active-pulse-crewai';
              } else {
                if (isActive) pulseClass = 'active-pulse';
              }

              const endpointTag = currentMode === 'dev'
                ? `<span class="text-emerald-400">● Engine ..${a.engine_id.slice(-6)}</span>`
                : (a.docker_live
                    ? `<span class="text-sky-400">🐳 :${a.port} LIVE</span>`
                    : `<span class="text-emerald-400">⚡ :${a.port} LIVE</span>`);

              return `
                <div onclick="selectAgent('${a.name}')" class="agent-node cursor-pointer glass-card rounded-xl p-2.5 border border-slate-800 hover:border-slate-600 ${pulseClass}">
                  <div class="flex items-center justify-between gap-1">
                    <span class="text-xs font-bold text-white truncate">${a.label}</span>
                    <span class="px-1.5 py-0.5 text-[9px] font-bold rounded border ${badgeClass}">${a.framework}</span>
                  </div>
                  <div class="mt-1 flex items-center justify-between text-[10px] mono text-slate-400">
                    <span>${a.id}</span>
                    ${endpointTag}
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    function selectAgent(agentName) {
      document.getElementById('target-agent-select').value = agentName;
      renderMesh([agentName]);
    }

    async function setMode(mode) {
      currentMode = mode;
      const devBtn = document.getElementById('mode-dev');
      const localBtn = document.getElementById('mode-local');
      if (mode === 'dev') {
        devBtn.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition bg-emerald-500/20 text-emerald-300 border border-emerald-500/40';
        localBtn.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition text-slate-400 hover:text-slate-200';
      } else {
        localBtn.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition bg-sky-500/20 text-sky-300 border border-sky-500/40';
        devBtn.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition text-slate-400 hover:text-slate-200';
      }
      await loadMesh();
    }

    function getTravelerName() {
      return (document.getElementById('user-id-input').value || '').trim() || 'sohil';
    }

    async function onTravelerChange() {
      const userId = getTravelerName();
      document.getElementById('user-id-input').value = userId;
      await startNewSession();
    }

    async function startNewSession() {
      const userId = getTravelerName();
      const res = await fetch('/api/new-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, mode: currentMode })
      });
      const data = await res.json();
      currentSessionId = data.session_id;
      STORY_STATE.outboundFlight = '';
      STORY_STATE.returnFlight = '';
      STORY_STATE.seat = '';
      STORY_STATE.hotel = 'Belmond Hotel Monasterio';
      document.getElementById('session-indicator').textContent = `Session: ${currentSessionId} (${userId})`;
      appendSystemBanner(`Started fresh session (${currentSessionId}) in ${currentMode.toUpperCase()} mode for traveler "${userId}".`);
    }

    function appendSystemBanner(text) {
      const stream = document.getElementById('chat-stream');
      const div = document.createElement('div');
      div.className = 'px-4 py-2 rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-xs text-indigo-200 mono';
      div.textContent = text;
      stream.appendChild(div);
      stream.scrollTop = stream.scrollHeight;
    }

    function runDemoAct(actNumber) {
      const prompt = getDemoPrompt(actNumber);
      if (!prompt) return;
      document.getElementById('prompt-input').value = prompt;
      sendPromptText(prompt);
    }

    function submitPrompt(e) {
      e.preventDefault();
      const input = document.getElementById('prompt-input');
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      sendPromptText(text);
    }

    async function sendPromptText(text) {
      const stream = document.getElementById('chat-stream');
      const userId = getTravelerName();
      const targetAgent = document.getElementById('target-agent-select').value;
      const sendBtn = document.getElementById('send-btn');

      const userDiv = document.createElement('div');
      userDiv.className = 'flex justify-end';
      userDiv.innerHTML = `
        <div class="max-w-2xl rounded-2xl rounded-tr-sm px-4 py-3 bg-gradient-to-r from-emerald-600/90 to-cyan-600/90 text-white text-sm shadow-lg">
          <div class="text-[10px] uppercase tracking-wider text-emerald-100 font-bold mb-1">Traveler (${userId}) → ${targetAgent} [${currentMode.toUpperCase()}]</div>
          <div>${text}</div>
        </div>
      `;
      stream.appendChild(userDiv);

      const loadingDiv = document.createElement('div');
      loadingDiv.className = 'glass-card rounded-2xl p-4 border border-slate-800 text-xs text-slate-300 flex items-center gap-3';
      loadingDiv.innerHTML = `
        <div class="w-3 h-3 rounded-full bg-emerald-400 animate-ping"></div>
        <span>Invoking <strong>${targetAgent}</strong> in <strong>${currentMode === 'dev' ? 'Dev (GCP Agent Runtime)' : 'Local (Docker / In-Memory)'}</strong> mode...</span>
      `;
      stream.appendChild(loadingDiv);
      stream.scrollTop = stream.scrollHeight;

      sendBtn.disabled = true;
      renderMesh([targetAgent]);

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: text,
            mode: currentMode,
            target_agent: targetAgent,
            user_id: userId,
            session_id: currentSessionId
          })
        });
        const data = await res.json();
        loadingDiv.remove();

        if (data.error) {
          const errDiv = document.createElement('div');
          errDiv.className = 'glass-card rounded-2xl p-4 border border-rose-500/40 text-xs text-rose-300 mono';
          errDiv.textContent = 'Error: ' + data.error;
          stream.appendChild(errDiv);
        } else {
          currentSessionId = data.session_id || currentSessionId;
          document.getElementById('session-indicator').textContent = `Session: ${currentSessionId} (${userId})`;
          document.getElementById('latency-badge').textContent = `${data.latency_ms} ms (${data.mode.toUpperCase()})`;

          syncStoryFromReply(data.reply || '');
          renderMesh(data.active_agents || [targetAgent]);

          const escapeHtml = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          const tLog = document.getElementById('telemetry-log');
          const events = data.ag_ui_events || [];
          const activeBadges = (data.active_agents || []).join(' → ');
          let logHtml = `<div class="p-2 rounded-lg bg-slate-900/90 border border-slate-800 space-y-1.5 mb-2">`;
          logHtml += `<div class="text-emerald-400 font-bold text-[11px]">[${new Date().toLocaleTimeString()}] [${data.mode.toUpperCase()}] Active A2A Chain: ${escapeHtml(activeBadges)} (${data.latency_ms} ms)</div>`;
          events.forEach(ev => {
            if (ev.kind === 'LOCAL_DOCKER_REGISTRY') {
              logHtml += `<div class="text-cyan-300 pl-2 text-[11px]">🐳 ${escapeHtml(ev.detail)}</div>`;
            } else if (ev.kind === 'A2A_JSONRPC_CALL') {
              logHtml += `
                <div class="pl-2 border-l-2 border-amber-500/50 py-0.5">
                  <div class="text-amber-300 font-semibold text-[11px]">📨 A2A Request: ${escapeHtml(ev.from_actor)} ➔ ${escapeHtml(ev.to_actor)} <span class="text-slate-500 font-normal">(${escapeHtml(ev.detail)})</span></div>
                  ${ev.message ? `<div class="text-slate-300 text-[11px] pl-2 mt-0.5 whitespace-pre-wrap break-words">"${escapeHtml(ev.message)}"</div>` : ''}
                </div>`;
            } else if (ev.kind === 'A2A_AGENT_MESSAGE') {
              const isReq = ev.direction === 'request';
              logHtml += `
                <div class="pl-2 border-l-2 ${isReq ? 'border-emerald-500/60' : 'border-purple-500/60'} py-0.5">
                  <div class="${isReq ? 'text-emerald-300' : 'text-purple-300'} font-semibold text-[11px]">
                    ${isReq ? '🔀 A2A Call (call_agent)' : '↩️ A2A Sub-Agent Reply'}: ${escapeHtml(ev.from_actor)} ➔ ${escapeHtml(ev.to_actor)}
                  </div>
                  <div class="text-slate-200 text-[11px] pl-2 mt-0.5 bg-slate-950/70 p-1.5 rounded border border-slate-800/80 whitespace-pre-wrap break-words">${escapeHtml(ev.message)}</div>
                </div>`;
            } else if (ev.kind === 'TOOL_CALL') {
              logHtml += `
                <div class="pl-2 border-l-2 border-sky-500/50 py-0.5">
                  <div class="text-sky-300 font-semibold text-[11px]">🔧 Tool Call: ${escapeHtml(ev.from_actor || targetAgent)} ➔ ${escapeHtml(ev.tool)}()</div>
                  <div class="text-slate-300 text-[11px] pl-2 mt-0.5 whitespace-pre-wrap break-words">${escapeHtml(JSON.stringify(ev.args || {}, null, 2))}</div>
                </div>`;
            } else if (ev.kind === 'TOOL_RESULT') {
              logHtml += `
                <div class="pl-2 border-l-2 border-teal-500/50 py-0.5">
                  <div class="text-teal-300 font-semibold text-[11px]">✅ Tool Result: ${escapeHtml(ev.tool)} ➔ ${escapeHtml(ev.to_actor || targetAgent)}</div>
                  <div class="text-slate-400 text-[11px] pl-2 mt-0.5 whitespace-pre-wrap break-words">${escapeHtml(JSON.stringify(ev.response || {}, null, 2))}</div>
                </div>`;
            } else if (ev.kind === 'A2A_FINAL_REPLY') {
              logHtml += `
                <div class="pl-2 border-l-2 border-emerald-400/50 py-0.5">
                  <div class="text-emerald-300 font-semibold text-[11px]">🏁 A2A Final Reply: ${escapeHtml(ev.from_actor)} ➔ ${escapeHtml(ev.to_actor)} (${ev.latency_ms} ms)</div>
                </div>`;
            }
          });
          logHtml += `</div>`;
          tLog.innerHTML = logHtml + tLog.innerHTML;

          const agentBadgesHtml = (data.active_agents || []).map(a => {
            let color = 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
            if (a === 'booking_agent') color = 'bg-amber-500/20 text-amber-300 border-amber-500/40';
            if (a === 'pre_trip_agent') color = 'bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40';
            return `<span class="px-2 py-0.5 rounded text-[10px] font-bold border ${color} mono">${a}</span>`;
          }).join(' ');

          const replyDiv = document.createElement('div');
          replyDiv.className = 'glass-card rounded-2xl p-5 border border-slate-800/90 shadow-xl';
          replyDiv.innerHTML = `
            <div class="flex items-center justify-between mb-2.5 flex-wrap gap-2">
              <div class="flex items-center gap-1.5 flex-wrap">
                <span class="text-xs font-extrabold text-white mr-1">AURA // VOYAGE</span>
                ${agentBadgesHtml}
              </div>
              <span class="text-[11px] mono text-slate-400">${data.latency_ms} ms • ${data.mode.toUpperCase()}</span>
            </div>
            <div class="prose prose-invert text-sm text-slate-200 max-w-none">${marked.parse(data.reply || '')}</div>
          `;
          stream.appendChild(replyDiv);
        }
      } catch (err) {
        loadingDiv.remove();
      } finally {
        sendBtn.disabled = false;
        stream.scrollTop = stream.scrollHeight;
      }
    }

    setMode(currentMode);
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (
        HTML_PAGE.replace("__DEFAULT_MODE__", DEFAULT_ENV_MODE)
        .replace("__DEFAULT_TRAVELER__", DEFAULT_TRAVELER)
    )
    return HTMLResponse(html)


def main() -> None:
    global DEFAULT_ENV_MODE, DEFAULT_TRAVELER
    parser = argparse.ArgumentParser(description="Start AURA // VOYAGE A2UI & AG-UI Travel Concierge Studio")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8090, help="Port to bind (default: 8090)")
    parser.add_argument(
        "--env",
        choices=["local", "dev"],
        default=os.environ.get("AURA_DEFAULT_MODE", "dev"),
        help="Default environment: 'local' (Docker Setup / .env) or 'dev' (GCP Agent Runtime / .env.dev)",
    )
    parser.add_argument(
        "--traveler",
        "--user-id",
        dest="traveler",
        default=os.environ.get("TRAVELER_NAME", "sohil"),
        help="Default traveler name / user_id (default: sohil)",
    )
    args = parser.parse_args()
    DEFAULT_ENV_MODE = args.env
    DEFAULT_TRAVELER = (args.traveler or "sohil").strip() or "sohil"

    print("\n" + "=" * 96)
    print(" ✨ AURA // VOYAGE — Polyglot A2UI & AG-UI Travel Concierge Studio")
    print("=" * 96)
    print(f" 🌐 Open in Browser : http://{args.host}:{args.port}")
    print(f" 👤 Traveler Name   : {DEFAULT_TRAVELER} (editable anytime in UI header)")
    print(f" 🎯 Default Env     : {DEFAULT_ENV_MODE.upper()} ({'GCP Agent Runtime (.env.dev)' if DEFAULT_ENV_MODE == 'dev' else 'Local Docker Setup (.env)'})")
    print(" 🔄 Live Switcher   : Toggle between 🐳 Local (Docker Setup) and ☁️ Dev (GCP Agent Runtime) in UI header")
    print("=" * 96 + "\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
