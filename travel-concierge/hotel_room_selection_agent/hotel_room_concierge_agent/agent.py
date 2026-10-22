import warnings
warnings.filterwarnings("ignore")
"""hotel_room_selection_agent — helps users with room choices for a hotel."""

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
from hotel_room_concierge_agent.schemas import RoomsSelection, json_response_config

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

HOTEL_ROOM_SELECTION_INSTR = """
Simulate available rooms for hotel chosen by the user, adjust pricing based on location/type of room.
- You must generate a non-empty response if the user chooses a hotel.
- Context hotel info: {hotel?}

When the hotel is in Cusco (such as Belmond Hotel Monasterio Cusco), ALWAYS return these 4 room choices so room names and rates ($450/night = $1,800 for 4 nights) match across the itinerary and checkout:
{{
  "rooms": [
    {{"is_available": true, "price_in_usd": 450, "room_type": "Deluxe Oxygen-Enriched Andean Suite"}},
    {{"is_available": true, "price_in_usd": 520, "room_type": "Junior Courtyard Suite (Oxygen-Enriched)"}},
    {{"is_available": true, "price_in_usd": 390, "room_type": "Superior King Room with Cloister View"}},
    {{"is_available": false, "price_in_usd": 850, "room_type": "Presidential Monasterio Suite"}}
  ]
}}
"""

root_agent = Agent(
    model=MODEL,
    name="hotel_room_selection_agent",
    description="Help users with room choices and pricing for a selected hotel.",
    instruction=HOTEL_ROOM_SELECTION_INSTR,
    output_schema=RoomsSelection,
    output_key="room",
    generate_content_config=json_response_config,
)


from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App
from hotel_room_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
    context_cache_config=ContextCacheConfig(),
)
