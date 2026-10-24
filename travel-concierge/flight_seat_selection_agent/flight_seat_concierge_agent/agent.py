import warnings
warnings.filterwarnings("ignore")
"""flight_seat_selection_agent — helps users with flight seat choices."""

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
from flight_seat_concierge_agent.schemas import SeatsSelection, json_response_config

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

FLIGHT_SEAT_SELECTION_INSTR = """
Simulate available seats for flight number specified by the user, 6 seats on each row and 3 rows in total (Row 12, Row 4, and Row 1), adjust pricing based on location of seat.
- You must generate a non-empty response if the user provides a flight number.
- Always include Row 12 (with window seat "12A" available at $60 USD — best unobstructed Andean mountain view ahead of the wing), Row 4 (with window seat "4A" available at $70 USD), and Row 1 (with window seat "1A" available at $80 USD).
- Context flight info: {flight?}

Example response format:
{{
  "seats": [
    [
      {{"is_available": true, "price_in_usd": 60, "seat_number": "12A"}},
      {{"is_available": false, "price_in_usd": 50, "seat_number": "12B"}},
      {{"is_available": true, "price_in_usd": 55, "seat_number": "12C"}},
      {{"is_available": true, "price_in_usd": 55, "seat_number": "12D"}},
      {{"is_available": false, "price_in_usd": 50, "seat_number": "12E"}},
      {{"is_available": true, "price_in_usd": 60, "seat_number": "12F"}}
    ],
    [
      {{"is_available": true, "price_in_usd": 70, "seat_number": "4A"}},
      {{"is_available": false, "price_in_usd": 60, "seat_number": "4B"}},
      {{"is_available": true, "price_in_usd": 65, "seat_number": "4C"}},
      {{"is_available": true, "price_in_usd": 65, "seat_number": "4D"}},
      {{"is_available": false, "price_in_usd": 60, "seat_number": "4E"}},
      {{"is_available": true, "price_in_usd": 70, "seat_number": "4F"}}
    ],
    [
      {{"is_available": true, "price_in_usd": 80, "seat_number": "1A"}},
      {{"is_available": false, "price_in_usd": 70, "seat_number": "1B"}},
      {{"is_available": false, "price_in_usd": 75, "seat_number": "1C"}},
      {{"is_available": true, "price_in_usd": 75, "seat_number": "1D"}},
      {{"is_available": false, "price_in_usd": 70, "seat_number": "1E"}},
      {{"is_available": true, "price_in_usd": 80, "seat_number": "1F"}}
    ]
  ]
}}
"""

root_agent = Agent(
    model=MODEL,
    name="flight_seat_selection_agent",
    include_contents="none",
    description="Help users with seat choices and pricing for a selected flight.",
    instruction=FLIGHT_SEAT_SELECTION_INSTR,
    output_schema=SeatsSelection,
    output_key="seat",
    generate_content_config=json_response_config,
)


from google.adk.apps.app import App
from flight_seat_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
)
