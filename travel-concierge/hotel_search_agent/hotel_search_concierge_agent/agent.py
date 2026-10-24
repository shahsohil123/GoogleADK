import warnings
warnings.filterwarnings("ignore")
"""hotel_search_agent — helps users find hotels around a specific geographic area."""

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
from hotel_search_concierge_agent.schemas import HotelsSelection, json_response_config

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

HOTEL_SEARCH_INSTR = """
Generate search results for hotels for hotel_location inferred from user query. Find only 4 results.
- Ask for any details you don't know, like check_in_date, check_out_date, places_of_interest.
- You must generate a non-empty JSON response if the user provides a hotel_location / destination.
- Current time: {_time?}
- User profile: {user_profile?}
- Origin: {origin?}, Destination: {destination?}

IMPORTANT — Canonical Luxury Hotels for Cusco, Peru:
When the destination is Cusco, Peru, ALWAYS return these exact 4 properties so downstream room selection, itinerary, and booking agents use identical names, addresses, and rates:
1. "Belmond Hotel Monasterio Cusco" — address: "Calle Palacio 136, Plazoleta Nazarenas, Cusco 08002, Peru", check_in_time: "15:00", check_out_time: "11:00", price: 450 ($450/night, $1,800 total for 4 nights — Recommended historic 16th-century monastery boutique hotel with oxygen-enriched suites and courtyard/Andean mountain views)
2. "Inkaterra La Casona Cusco" — address: "Plaza las Nazarenas 211, Cusco 08002, Peru", check_in_time: "15:00", check_out_time: "11:00", price: 520
3. "Palacio del Inka, a Luxury Collection Hotel, Cusco" — address: "Plazoleta Santo Domingo 259, Cusco 08002, Peru", check_in_time: "15:00", check_out_time: "11:00", price: 380
4. "JW Marriott El Convento Cusco" — address: "Esquina de la Calle Ruinas 432, Cusco 08002, Peru", check_in_time: "15:00", check_out_time: "11:00", price: 350

Return the response as a JSON object formatted like this:
{{
  "hotels": [
    {{
      "name": "Name of the hotel",
      "address": "Full address of the Hotel",
      "check_in_time": "15:00",
      "check_out_time": "11:00",
      "thumbnail": "/src/images/hotel.png",
      "price": 450
    }}
  ]
}}
"""

root_agent = Agent(
    model=MODEL,
    name="hotel_search_agent",
    include_contents="none",
    description="Help users find hotels around a specific geographic area or destination.",
    instruction=HOTEL_SEARCH_INSTR,
    output_schema=HotelsSelection,
    output_key="hotel",
    generate_content_config=json_response_config,
)


from google.adk.apps.app import App
from hotel_search_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
)
