import warnings
warnings.filterwarnings("ignore")
"""itinerary_agent — creates and persists a structured JSON representation of the itinerary."""

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
from itinerary_concierge_agent.schemas import Itinerary, json_response_config

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

ITINERARY_AGENT_INSTR = """
Given a full itinerary plan provided by the planning agent or caller, generate a JSON object capturing that plan.

Context details (also inspect the caller's request message for full flight/hotel/activity details):
  <origin>{origin?}</origin>
  <destination>{destination?}</destination>
  <start_date>{start_date?}</start_date>
  <end_date>{end_date?}</end_date>
  <outbound_flight_selection>{outbound_flight_selection?}</outbound_flight_selection>
  <outbound_seat_number>{outbound_seat_number?}</outbound_seat_number>
  <return_flight_selection>{return_flight_selection?}</return_flight_selection>
  <return_seat_number>{return_seat_number?}</return_seat_number>
  <hotel_selection>{hotel_selection?}</hotel_selection>
  <room_selection>{room_selection?}</room_selection>

Current time: {_time?}; Infer the Year from the time.

The JSON object captures:
- Metadata: trip_name, start_date, end_date, origin, destination.
- Multi-day itinerary (`days`), each with `day_number`, `date` (YYYY-MM-DD), and `events` (`flight`, `hotel`, `visit`).
- Always use empty strings "" instead of null.
"""

root_agent = Agent(
    model=MODEL,
    name="itinerary_agent",
    description="Create and return a structured multi-day JSON representation of the travel itinerary.",
    instruction=ITINERARY_AGENT_INSTR,
    output_schema=Itinerary,
    output_key="itinerary",
    generate_content_config=json_response_config,
)


from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App
from itinerary_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
    context_cache_config=ContextCacheConfig(),
)
