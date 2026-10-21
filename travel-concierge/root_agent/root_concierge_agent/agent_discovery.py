"""Dynamic agent discovery via Google Cloud Agent Registry (`discover_agents`
and `call_agent`), propagating the caller's `user_id` via `X-User-Id` so
downstream A2A agents access the same Session Service and Memory Bank scope,
and recording OpenTelemetry spans exported to Google Cloud Trace.

How Agent Registry works across Cloud and Local modes:
- **Cloud Mode (`LOCAL_MODE=false`)**: Queries live Google Cloud Agent Registry
  (`https://agentregistry.googleapis.com/v1/projects/{project}/locations/{location}/agents:search`).
- **Local Docker Mode (`docker-compose.yml`)**: Queries the `local_agent_registry`
  container (`AGENT_REGISTRY_BASE_URL=http://local_agent_registry:8000/v1`) which
  implements the exact Google Cloud Agent Registry v1 REST API (`agents:search`,
  `agents`, `agents/{id}`, `bindings`) pointing to each local A2A container
  (`http://inspiration_agent:8002`, `http://booking_agent:8004`, etc.).
- **Local Host / Eval Mode (`LOCAL_MODE=true`)**: Uses `AgentRegistry` (`search_agents`,
  `list_agents`, `get_remote_a2a_agent`) backed by the local v1 Agent Registry
  catalog (`http://localhost:8001..8016`) whenever the local emulator or cloud
  deployment is not yet populated.
"""

import asyncio
import json
import os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True), override=False)

from typing import Any, Dict, List

import requests
from opentelemetry import trace
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.tools import FunctionTool, ToolContext
from google.adk.tools.agent_tool import AgentTool

from root_concierge_agent.auth import build_authed_httpx_client, current_user_id
from root_concierge_agent.vertex_services import is_local_mode

_tracer = trace.get_tracer("travel_concierge.agent_discovery")

_NOT_CALLABLE_AGENTS = {
    "travel-concierge-shared-state",
    "travel-concierge-memory-bank",
}

_LOCAL_AGENT_CATALOG: Dict[str, Dict[str, Any]] = {
    "root_agent": {
        "port": 8001,
        "description": "Root Travel Concierge orchestrator coordinating all travel phases.",
        "tags": ["root", "concierge", "orchestrator", "travel"],
    },
    "inspiration_agent": {
        "port": 8002,
        "description": "Travel inspiration coordinator helping users discover dream destinations and activities (place_agent, poi_agent).",
        "tags": ["inspiration", "dream", "destination", "ideas", "poi", "activities"],
    },
    "planning_agent": {
        "port": 8003,
        "description": "Travel planning coordinator handling flight search, seat selection, hotel search, room selection, and full travel itineraries.",
        "tags": ["planning", "itinerary", "flights", "hotels", "seats", "rooms", "deals"],
    },
    "booking_agent": {
        "port": 8004,
        "description": "LangGraph booking and payment agent that creates reservations, shows payment choices, and processes payments.",
        "tags": ["booking", "reservation", "payment", "checkout", "confirm", "langgraph"],
    },
    "pre_trip_agent": {
        "port": 8005,
        "description": "CrewAI pre-trip readiness crew providing visa, medical, storm, travel advisories, and packing lists.",
        "tags": ["pre_trip", "pretrip", "packing", "visa", "medical", "weather", "advisory", "crewai"],
    },
    "in_trip_agent": {
        "port": 8006,
        "description": "In-trip concierge providing day-of transit logistics, flight/event/weather monitoring, and real-time itinerary changes.",
        "tags": ["in_trip", "intrip", "transit", "monitor", "flight_status", "day_of", "schedule"],
    },
    "post_trip_agent": {
        "port": 8007,
        "description": "Post-trip agent collecting trip feedback, reviews, and extracting traveler preferences into Memory Bank.",
        "tags": ["post_trip", "posttrip", "feedback", "review", "preferences", "memory"],
    },
    "place_agent": {
        "port": 8008,
        "description": "Destination place suggestions specialist returning structured DestinationIdeas.",
        "tags": ["place", "destination", "countries", "cities", "inspiration"],
    },
    "poi_agent": {
        "port": 8009,
        "description": "Points of Interest (POI) and landmarks specialist with Google Maps Grounding Lite MCP.",
        "tags": ["poi", "attractions", "landmarks", "activities", "maps"],
    },
    "flight_search_agent": {
        "port": 8010,
        "description": "Flight search specialist returning structured FlightsSelection options.",
        "tags": ["flight_search", "flights", "airlines", "departure", "arrival"],
    },
    "flight_seat_selection_agent": {
        "port": 8011,
        "description": "Flight cabin seat map and seat selection specialist returning SeatsSelection.",
        "tags": ["flight_seat_selection", "seat", "seats", "window", "aisle", "cabin"],
    },
    "hotel_search_agent": {
        "port": 8012,
        "description": "Hotel and accommodation search specialist returning structured HotelsSelection.",
        "tags": ["hotel_search", "hotels", "accommodation", "resort", "stay"],
    },
    "hotel_room_selection_agent": {
        "port": 8013,
        "description": "Hotel room category and rate selection specialist returning RoomsSelection.",
        "tags": ["hotel_room_selection", "room", "rooms", "suite", "king", "twin"],
    },
    "itinerary_agent": {
        "port": 8014,
        "description": "Full multi-day travel itinerary compiler returning structured Itinerary JSON.",
        "tags": ["itinerary", "schedule", "day_by_day", "plan"],
    },
    "day_of_agent": {
        "port": 8015,
        "description": "Day-of transit and ground transportation routing specialist.",
        "tags": ["day_of", "transit", "transportation", "directions", "transfer"],
    },
    "trip_monitor_agent": {
        "port": 8016,
        "description": "Flight status, event booking, and weather impact monitoring specialist.",
        "tags": ["trip_monitor", "flight_status", "weather_impact", "event_booking", "delays"],
    },
}


class HybridAgentRegistry(AgentRegistry):
    """Subclasses ADK's `AgentRegistry` to support both Google Cloud Agent Registry
    (`https://agentregistry.googleapis.com/v1`) and local Docker / host execution
    (`AGENT_REGISTRY_BASE_URL` or built-in local v1 catalog when `LOCAL_MODE=true`).
    """

    def __init__(self, project_id: str, location: str):
        if is_local_mode():
            # Stateless local mode: do NOT call google.auth.default() or connect to GCP Agent Registry
            self.project_id = project_id or "local-project"
            self.location = location or "global"
            self._base_path = f"projects/{self.project_id}/locations/{self.location}"
            self._header_provider = None
            self._use_mtls = False
            self._base_url = os.environ.get("AGENT_REGISTRY_BASE_URL", "http://localhost:8000/v1").rstrip("/")
        else:
            super().__init__(project_id=project_id, location=location)
            custom_base_url = os.environ.get("AGENT_REGISTRY_BASE_URL")
            if custom_base_url:
                self._base_url = custom_base_url.rstrip("/")

    def _resolve_auth_provider_scheme(self, resource_id, resource_name, *, continue_uri=None):
        if is_local_mode():
            return None
        return super()._resolve_auth_provider_scheme(
            resource_id, resource_name, continue_uri=continue_uri
        )

    def _build_local_entry(self, agent_id: str) -> Dict[str, Any]:
        meta = _LOCAL_AGENT_CATALOG[agent_id]
        use_docker = os.environ.get("DOCKER_NETWORK_MODE", "false").lower() in ("true", "1", "yes")
        host = agent_id if use_docker else "localhost"
        url = os.environ.get(f"{agent_id.upper()}_URL", f"http://{host}:{meta['port']}/a2a")
        return {
            "name": f"{self._base_path}/agents/{agent_id}",
            "agentId": agent_id,
            "location": self.location,
            "displayName": agent_id,
            "description": meta["description"],
            "version": "1.0.0",
            "protocols": [
                {
                    "type": "A2A_AGENT",
                    "protocolVersion": "1.0",
                    "interfaces": [
                        {
                            "url": url,
                            "protocolBinding": "JSONRPC",
                        }
                    ],
                }
            ],
            "skills": [
                {
                    "id": f"{agent_id}_skill",
                    "name": agent_id,
                    "description": meta["description"],
                    "tags": meta["tags"],
                    "examples": [f"Ask {agent_id} for help"],
                }
            ],
        }

    def _local_fallback_request(
        self,
        path: str,
        method: str = "GET",
        params: Dict[str, Any] | None = None,
        json_data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if path.endswith("agents:search") and method == "POST":
            q = (json_data or {}).get("searchString", "")
            tokens = [t for t in q.lower().replace("-", "_").replace(",", " ").split() if t]
            entries = [self._build_local_entry(aid) for aid in _LOCAL_AGENT_CATALOG]
            if not tokens:
                return {"agents": entries}
            matched = []
            for e in entries:
                haystack = " ".join([
                    e["agentId"].lower(),
                    e["displayName"].lower(),
                    e["description"].lower(),
                    " ".join(e["skills"][0]["tags"]).lower(),
                ])
                if any(tok in haystack for tok in tokens):
                    matched.append(e)
            return {"agents": matched}

        if path == "agents" or path.endswith("/agents"):
            return {"agents": [self._build_local_entry(aid) for aid in _LOCAL_AGENT_CATALOG]}

        if path == "bindings" or path.endswith("/bindings"):
            return {"bindings": []}

        if path in _LOCAL_AGENT_CATALOG:
            return self._build_local_entry(path)

        if "/agents/" in path:
            agent_id = path.rsplit("/agents/", 1)[-1]
            if agent_id in _LOCAL_AGENT_CATALOG:
                return self._build_local_entry(agent_id)

        return {}

    def _make_request(
        self,
        path: str,
        method: str = "GET",
        params: Dict[str, Any] | None = None,
        json_data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if path in _LOCAL_AGENT_CATALOG:
            path = f"{self._base_path}/agents/{path}"
        custom_base_url = os.environ.get("AGENT_REGISTRY_BASE_URL")
        if custom_base_url:
            # Call the local Agent Registry emulator container directly over HTTP
            url = f"{custom_base_url.rstrip('/')}/{path if path.startswith('projects/') else f'{self._base_path}/{path}'}"
            try:
                if method == "POST":
                    resp = requests.post(url, json=json_data, timeout=5)
                else:
                    resp = requests.get(url, params=params, timeout=5)
                resp.raise_for_status()
                return resp.json()
            except Exception:
                return self._local_fallback_request(path, method, params, json_data)

        if is_local_mode():
            return self._local_fallback_request(path, method, params, json_data)

        try:
            data = super()._make_request(path, method=method, params=params, json_data=json_data)
            if isinstance(data, dict):
                eng_loc = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
                raw_json = (
                    json.dumps(data)
                    .replace("global-aiplatform.googleapis.com", f"{eng_loc}-aiplatform.googleapis.com")
                    .replace("/locations/global/reasoningEngines/", f"/locations/{eng_loc}/reasoningEngines/")
                    .replace('"streaming": true', '"streaming": false')
                )
                data = json.loads(raw_json)
            # If searching/listing in cloud before the 16 agents are deployed, merge local entries if empty
            if "agents" in path and not any(
                a.get("displayName", "").replace("-", "_").removesuffix("_a2a") in _LOCAL_AGENT_CATALOG
                or a.get("displayName") in _LOCAL_AGENT_CATALOG
                for a in data.get("agents", [])
            ):
                local_data = self._local_fallback_request(path, method, params, json_data)
                if local_data:
                    return local_data
            return data
        except Exception:
            return self._local_fallback_request(path, method, params, json_data)


_registry = HybridAgentRegistry(
    project_id=os.environ.get("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id"),
    location=os.environ.get("AGENT_REGISTRY_LOCATION", "global"),
)
_httpx_client = build_authed_httpx_client()
_agent_tool_cache: dict[str, AgentTool] = {}
_resolved_name_cache: dict[str, str] = {}


def _fresh_agent_tool(agent_name: str) -> AgentTool:
    remote_agent = _registry.get_remote_a2a_agent(agent_name=agent_name, httpx_client=_httpx_client)
    return AgentTool(agent=remote_agent)


def _to_match(agent: dict) -> dict:
    return {
        "agent_name": agent["name"],
        "display_name": agent.get("displayName", ""),
        "description": agent.get("description", ""),
        "skills": [
            {"name": s.get("name"), "description": s.get("description")}
            for s in agent.get("skills", [])
        ],
    }


def _is_callable_a2a_agent(agent: dict, own_name: str | None) -> bool:
    display_name = agent.get("displayName", "")
    if display_name in _NOT_CALLABLE_AGENTS or display_name == own_name:
        return False
    return any(p.get("type") == "A2A_AGENT" for p in agent.get("protocols", []))


async def discover_agents(capability: str, tool_context: ToolContext) -> dict:
    """Find specialist A2A agents in Google Cloud Agent Registry that can help with a task.

    Searches Google Cloud Agent Registry via `_registry.search_agents(search_string=capability,
    search_type="KEYWORD")` and falls back to keyword matching across `_registry.list_agents()`.

    Args:
        capability: A short description or name of the specialist capability you need.
    """
    own_name = tool_context._invocation_context.agent.name if tool_context._invocation_context else None

    with _tracer.start_as_current_span("agent_registry.discover_agents") as span:
        span.set_attribute("adk.agent_registry.capability_query", capability)
        span.set_attribute("adk.agent_registry.caller_agent", own_name or "unknown")

        result = _registry.search_agents(search_string=capability, search_type="KEYWORD")
        matches = [
            _to_match(agent) for agent in result.get("agents", []) if _is_callable_a2a_agent(agent, own_name)
        ]

        if not matches:
            words = [w for w in capability.lower().replace("_", " ").split() if len(w) > 2]
            all_agents = _registry.list_agents().get("agents", [])
            for agent in all_agents:
                if not _is_callable_a2a_agent(agent, own_name):
                    continue
                haystack = " ".join(
                    [agent.get("displayName", ""), agent.get("description", "")]
                    + [s.get("description", "") for s in agent.get("skills", [])]
                ).lower()
                if any(word in haystack for word in words):
                    matches.append(_to_match(agent))

        span.set_attribute("adk.agent_registry.matches_count", len(matches))
        if not matches:
            return {"found": False, "matches": []}
        return {"found": True, "matches": matches}


_recent_agent_calls: dict[tuple[str, str], tuple[float, asyncio.Future]] = {}
_SINGLE_CALL_PER_TURN_AGENTS = {
    "place_agent",
    "poi_agent",
    "flight_search_agent",
    "hotel_search_agent",
    "itinerary_agent",
}


async def call_agent(agent_name: str, message: str, tool_context: ToolContext) -> str:
    """Send a message to a discovered A2A agent in Google Cloud Agent Registry and return its reply.

    Forwards the current traveler's `user_id` in `X-User-Id` so the remote agent
    shares the same Session Service and Memory Bank identity.

    Args:
        agent_name: The `agent_name` resource name or specialist agent identifier (e.g. `place_agent`).
        message: The prompt and context to send to that agent.
    """
    uid = "default"
    if tool_context._invocation_context and getattr(tool_context._invocation_context, "user_id", None):
        uid = tool_context._invocation_context.user_id
        current_user_id.set(uid)

    if not agent_name.startswith("projects/"):
        if agent_name in _resolved_name_cache:
            agent_name = _resolved_name_cache[agent_name]
        else:
            disc = await discover_agents(agent_name, tool_context)
            if disc.get("found") and disc.get("matches"):
                _resolved_name_cache[agent_name] = disc["matches"][0]["agent_name"]
                agent_name = _resolved_name_cache[agent_name]

    short_name = agent_name.rsplit("/", 1)[-1]
    dedup_key = (
        (uid, short_name)
        if short_name in _SINGLE_CALL_PER_TURN_AGENTS
        else (uid, short_name, message.strip()[:160])
    )
    now = asyncio.get_running_loop().time()
    cached = _recent_agent_calls.get(dedup_key)
    if cached is not None:
        ts, fut = cached
        if now - ts < 8.0 and not fut.cancelled():
            if not fut.done() or not fut.exception():
                return await asyncio.shield(fut)

    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    _recent_agent_calls[dedup_key] = (now, fut)

    try:
        with _tracer.start_as_current_span("agent_registry.call_agent") as span:
            span.set_attribute("adk.agent_registry.target_agent", agent_name)
            response = ""
            for attempt in range(4):
                agent_tool = _agent_tool_cache.get(agent_name)
                if agent_tool is None or attempt > 0:
                    agent_tool = _agent_tool_cache[agent_name] = _fresh_agent_tool(agent_name)
                response = await agent_tool.run_async(args={"request": message}, tool_context=tool_context)
                is_unrecoverable = (
                    "timed out" in response.lower()
                    or "timeout" in response.lower()
                    or "all connection attempts failed" in response.lower()
                )
                is_retryable = not is_unrecoverable and (
                    response.startswith("A2A request failed")
                    or ("429" in response and "RESOURCE_EXHAUSTED" in response)
                )
                if not is_retryable:
                    break
                if attempt < 3:
                    await asyncio.sleep(2.0 * (2 ** attempt))
            fut.set_result(response)
            return response
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        _recent_agent_calls.pop(dedup_key, None)
        raise


discover_agents_tool = FunctionTool(discover_agents)
call_agent_tool = FunctionTool(call_agent)

