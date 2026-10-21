import warnings
warnings.filterwarnings("ignore")
"""day_of_agent — handles day-of travel logistics and transit coordination."""

from datetime import datetime
from typing import Any
import os
from dotenv import load_dotenv

load_dotenv()

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
os.environ["ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"

from google.adk.agents import Agent
from day_of_concierge_agent.state_helpers import DEFAULT_USER_PROFILE, ensure_default_state

from google.adk.models.google_llm import Gemini
from google.genai import types as _genai_types

MODEL = Gemini(
    model=os.environ.get("GENAI_MODEL", "gemini-3-flash-preview"),
    retry_options=_genai_types.HttpRetryOptions(
        attempts=5,
        initial_delay=2.0,
        max_delay=30.0,
        exp_base=2.0,
        http_status_codes=[429, 500, 502, 503, 504],
    ),
)


def _get_event_time_as_destination(destin_json: dict[str, Any], default_value: str) -> str:
    event_type = destin_json.get("event_type")
    if event_type == "flight":
        return destin_json.get("boarding_time", default_value)
    if event_type == "hotel":
        return destin_json.get("check_in_time", default_value)
    if event_type == "visit":
        return destin_json.get("start_time", default_value)
    return default_value


def _parse_as_origin(origin_json: dict[str, Any]) -> tuple[str, str]:
    event_type = origin_json.get("event_type")
    if event_type == "flight":
        return (
            origin_json.get("arrival_airport", "") + " Airport",
            origin_json.get("arrival_time", "any time"),
        )
    if event_type == "hotel":
        return (
            f"{origin_json.get('description', '')} {origin_json.get('address', '')}".strip(),
            "any time",
        )
    if event_type == "visit":
        return (
            f"{origin_json.get('description', '')} {origin_json.get('address', '')}".strip(),
            origin_json.get("end_time", "any time"),
        )
    if event_type == "home":
        return (
            f"{origin_json.get('local_prefer_mode', 'drive')} from {origin_json.get('address', '')}",
            "any time",
        )
    return "Local in the region", "any time"


def _parse_as_destin(destin_json: dict[str, Any]) -> tuple[str, str]:
    event_type = destin_json.get("event_type")
    if event_type == "flight":
        return (
            destin_json.get("departure_airport", "") + " Airport",
            "An hour before " + destin_json.get("boarding_time", ""),
        )
    if event_type == "hotel":
        return (
            f"{destin_json.get('description', '')} {destin_json.get('address', '')}".strip(),
            "any time",
        )
    if event_type == "visit":
        return (
            f"{destin_json.get('description', '')} {destin_json.get('address', '')}".strip(),
            destin_json.get("start_time", "as soon as possible"),
        )
    if event_type == "home":
        return (
            f"{destin_json.get('local_prefer_mode', 'drive')} to {destin_json.get('address', '')}",
            "any time",
        )
    return "Local in the region", "as soon as possible"


def calculate_transit_segment(itinerary: dict[str, Any], current_datetime: str, home_address: str = "") -> dict[str, str]:
    """Find the immediate next movement segment (FROM, TO, LEAVE_BY, ARRIVE_BY) given an itinerary and current datetime (YYYY-MM-DD HH:MM)."""
    try:
        datetime_object = datetime.fromisoformat(current_datetime)
    except ValueError:
        datetime_object = datetime.now()
    current_date = datetime_object.strftime("%Y-%m-%d")
    current_time = datetime_object.strftime("%H:%M")

    home = DEFAULT_USER_PROFILE["home"].copy()
    if home_address:
        home["address"] = home_address

    origin_json = home
    destin_json = home

    for day in itinerary.get("days", []):
        event_date = day.get("date", current_date)
        for event in day.get("events", []):
            origin_json = destin_json
            destin_json = event
            event_time = _get_event_time_as_destination(destin_json, current_time)
            if event_date >= current_date and event_time >= current_time:
                break
        else:
            continue
        break

    travel_from, leave_by = _parse_as_origin(origin_json)
    travel_to, arrive_by = _parse_as_destin(destin_json)
    return {
        "current_time": current_datetime,
        "travel_from": travel_from,
        "leave_by_time": leave_by,
        "travel_to": travel_to,
        "arrive_by_time": arrive_by,
    }


DAY_OF_INSTR = """
Your role is primarily to handle day-of logistics to get to the next destination on a traveler's trip.

If the caller provides an itinerary and current time in the message, you can call `calculate_transit_segment` or inspect the next segment directly:
- If FROM is the same as TO, inform the traveler that there is nothing to do.
- If ARRIVE_BY is far from Current Time, inform them we don't have anything urgent to work on yet.
- If ARRIVE_BY is "as soon as possible" or in the immediate future:
  - Suggest the best transportation mode and the best time to depart the starting FROM place in order to reach the TO place on time.
  - If the destination in TO is an airport, provide extra buffer time for parking and security checks.
  - If the destination in TO is reachable by Uber, offer to order one, estimate the ETA, and suggest a pickup point.
"""

root_agent = Agent(
    model=MODEL,
    name="day_of_agent",
    description="Day_of agent handling the day-of travel logistics and transit coordination of a trip.",
    instruction=DAY_OF_INSTR,
    tools=[calculate_transit_segment],
    generate_content_config=_genai_types.GenerateContentConfig(
        thinking_config=_genai_types.ThinkingConfig(thinking_level="LOW"),
    ),
    before_agent_callback=ensure_default_state,
)


from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App
from day_of_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
    context_cache_config=ContextCacheConfig(),
)
