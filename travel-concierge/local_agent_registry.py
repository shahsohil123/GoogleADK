"""Local Google Cloud Agent Registry v1 Emulator (`agentregistry.googleapis.com/v1`).

When running locally (via `docker-compose.yml`, `run_local.py`, or `adk eval`),
Google Cloud Agent Registry (`https://agentregistry.googleapis.com/v1`) in GCP
only indexes agents that have already been deployed to Vertex AI Agent Engine,
and its URLs point to cloud Reasoning Engine endpoints rather than local
containers (`http://localhost:8001..8016` or `http://<agent>:8001..8016`).

This module provides:
1. A FastAPI server implementing the exact Google Cloud Agent Registry v1 REST endpoints:
   - `POST /v1/projects/{project}/locations/{location}/agents:search`
   - `GET  /v1/projects/{project}/locations/{location}/agents`
   - `GET  /v1/projects/{project}/locations/{location}/agents/{agent_id}`
   - `GET  /v1/projects/{project}/locations/{location}/bindings`
   so that ADK's `google.adk.integrations.agent_registry.AgentRegistry` works
   unmodified against local Docker containers or local processes.
2. In-memory search/get helpers used by `agent_discovery.py` when `LOCAL_MODE=true`.
"""

import os
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException, Query, Request

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id")
LOCATION = os.environ.get("AGENT_REGISTRY_LOCATION", "global")
DOCKER_NETWORK_MODE = os.environ.get("DOCKER_NETWORK_MODE", "false").lower() in ("true", "1", "yes")

AGENT_CATALOG: Dict[str, Dict[str, Any]] = {
    "root_agent": {
        "port": 8001,
        "framework": "google_adk",
        "description": "Root Travel Concierge orchestrator coordinating all travel phases.",
        "tags": ["root", "concierge", "orchestrator", "travel"],
    },
    "inspiration_agent": {
        "port": 8002,
        "framework": "google_adk",
        "description": "Travel inspiration coordinator helping users discover dream destinations and activities (place_agent, poi_agent).",
        "tags": ["inspiration", "dream", "destination", "ideas", "poi", "activities"],
    },
    "planning_agent": {
        "port": 8003,
        "framework": "google_adk",
        "description": "Travel planning coordinator handling flight search, seat selection, hotel search, room selection, and full travel itineraries.",
        "tags": ["planning", "itinerary", "flights", "hotels", "seats", "rooms", "deals"],
    },
    "booking_agent": {
        "port": 8004,
        "framework": "langgraph",
        "description": "LangGraph booking and payment agent that creates reservations, shows payment choices, and processes payments.",
        "tags": ["booking", "reservation", "payment", "checkout", "confirm", "langgraph"],
    },
    "pre_trip_agent": {
        "port": 8005,
        "framework": "crewai",
        "description": "CrewAI pre-trip readiness crew providing visa, medical, storm, travel advisories, and packing lists.",
        "tags": ["pre_trip", "pretrip", "packing", "visa", "medical", "weather", "advisory", "crewai"],
    },
    "in_trip_agent": {
        "port": 8006,
        "framework": "google_adk",
        "description": "In-trip concierge providing day-of transit logistics, flight/event/weather monitoring, and real-time itinerary changes.",
        "tags": ["in_trip", "intrip", "transit", "monitor", "flight_status", "day_of", "schedule"],
    },
    "post_trip_agent": {
        "port": 8007,
        "framework": "google_adk",
        "description": "Post-trip agent collecting trip feedback, reviews, and extracting traveler preferences into Memory Bank.",
        "tags": ["post_trip", "posttrip", "feedback", "review", "preferences", "memory"],
    },
    "place_agent": {
        "port": 8008,
        "framework": "google_adk",
        "description": "Destination place suggestions specialist returning structured DestinationIdeas.",
        "tags": ["place", "destination", "countries", "cities", "inspiration"],
    },
    "poi_agent": {
        "port": 8009,
        "framework": "google_adk",
        "description": "Points of Interest (POI) and landmarks specialist with Google Maps Grounding Lite MCP.",
        "tags": ["poi", "attractions", "landmarks", "activities", "maps"],
    },
    "flight_search_agent": {
        "port": 8010,
        "framework": "google_adk",
        "description": "Flight search specialist returning structured FlightsSelection options.",
        "tags": ["flight_search", "flights", "airlines", "departure", "arrival"],
    },
    "flight_seat_selection_agent": {
        "port": 8011,
        "framework": "google_adk",
        "description": "Flight cabin seat map and seat selection specialist returning SeatsSelection.",
        "tags": ["flight_seat_selection", "seat", "seats", "window", "aisle", "cabin"],
    },
    "hotel_search_agent": {
        "port": 8012,
        "framework": "google_adk",
        "description": "Hotel and accommodation search specialist returning structured HotelsSelection.",
        "tags": ["hotel_search", "hotels", "accommodation", "resort", "stay"],
    },
    "hotel_room_selection_agent": {
        "port": 8013,
        "framework": "google_adk",
        "description": "Hotel room category and rate selection specialist returning RoomsSelection.",
        "tags": ["hotel_room_selection", "room", "rooms", "suite", "king", "twin"],
    },
    "itinerary_agent": {
        "port": 8014,
        "framework": "google_adk",
        "description": "Full multi-day travel itinerary compiler returning structured Itinerary JSON.",
        "tags": ["itinerary", "schedule", "day_by_day", "plan"],
    },
    "day_of_agent": {
        "port": 8015,
        "framework": "google_adk",
        "description": "Day-of transit and ground transportation routing specialist.",
        "tags": ["day_of", "transit", "transportation", "directions", "transfer"],
    },
    "trip_monitor_agent": {
        "port": 8016,
        "framework": "google_adk",
        "description": "Flight status, event booking, and weather impact monitoring specialist.",
        "tags": ["trip_monitor", "flight_status", "weather_impact", "event_booking", "delays"],
    },
}


def build_agent_registry_entry(
    agent_id: str,
    project_id: str = PROJECT_ID,
    location: str = LOCATION,
    use_docker_hostnames: bool = DOCKER_NETWORK_MODE,
) -> Dict[str, Any]:
    """Builds a Google Cloud Agent Registry v1 compliant Agent resource dict."""
    meta = AGENT_CATALOG[agent_id]
    port = meta["port"]
    host = agent_id if use_docker_hostnames else "localhost"
    env_url = os.environ.get(f"{agent_id.upper()}_URL")
    url = env_url or f"http://{host}:{port}/a2a"

    return {
        "name": f"projects/{project_id}/locations/{location}/agents/{agent_id}",
        "agentId": agent_id,
        "location": location,
        "displayName": agent_id,
        "description": meta["description"],
        "version": "1.0.0",
        "attributes": {
            "framework": meta["framework"],
            "local_port": port,
        },
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


def search_local_registry_entries(
    search_string: str | None = None,
    project_id: str = PROJECT_ID,
    location: str = LOCATION,
    use_docker_hostnames: bool = DOCKER_NETWORK_MODE,
) -> List[Dict[str, Any]]:
    """Performs keyword search across the 16 registered A2A agents (matching `agents:search`)."""
    all_entries = [
        build_agent_registry_entry(aid, project_id, location, use_docker_hostnames)
        for aid in AGENT_CATALOG
    ]
    if not search_string or not search_string.strip():
        return all_entries

    tokens = [
        t for t in search_string.lower().replace("-", "_").replace(",", " ").split() if t
    ]
    matched: List[Dict[str, Any]] = []
    for entry in all_entries:
        haystack = " ".join([
            entry["agentId"].lower(),
            entry["displayName"].lower(),
            entry["description"].lower(),
            " ".join(entry["skills"][0]["tags"]).lower(),
        ])
        if any(tok in haystack for tok in tokens):
            matched.append(entry)
    return matched or all_entries


app = FastAPI(
    title="Local Google Cloud Agent Registry v1 Emulator",
    description="Emulates https://agentregistry.googleapis.com/v1 for local Docker & ADK development.",
    version="1.0.0",
)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "registered_agents": len(AGENT_CATALOG)}


@app.post("/v1/projects/{project_id}/locations/{location}/agents:search")
async def search_agents_endpoint(
    project_id: str,
    location: str,
    request: Request,
) -> Dict[str, Any]:
    body = await request.json() if await request.body() else {}
    search_string = body.get("searchString", "")
    agents = search_local_registry_entries(
        search_string=search_string,
        project_id=project_id,
        location=location,
    )
    return {"agents": agents}


@app.get("/v1/projects/{project_id}/locations/{location}/agents")
async def list_agents_endpoint(
    project_id: str,
    location: str,
    filter: str | None = Query(default=None),
) -> Dict[str, Any]:
    agents = search_local_registry_entries(
        search_string=filter,
        project_id=project_id,
        location=location,
    )
    return {"agents": agents}


@app.get("/v1/projects/{project_id}/locations/{location}/agents/{agent_id}")
async def get_agent_endpoint(
    project_id: str,
    location: str,
    agent_id: str,
) -> Dict[str, Any]:
    if agent_id not in AGENT_CATALOG:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in local registry")
    return build_agent_registry_entry(
        agent_id=agent_id,
        project_id=project_id,
        location=location,
    )


@app.get("/v1/projects/{project_id}/locations/{location}/bindings")
async def list_bindings_endpoint(project_id: str, location: str) -> Dict[str, Any]:
    return {"bindings": []}
