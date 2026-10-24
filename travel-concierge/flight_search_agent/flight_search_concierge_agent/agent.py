import warnings
warnings.filterwarnings("ignore")
"""flight_search_agent — helps users find best flight deals."""

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
from flight_search_concierge_agent.schemas import FlightsSelection, json_response_config

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

FLIGHT_SEARCH_INSTR = """
Generate search results for flights from origin to destination inferred from user query. Use the exact travel dates specified by the user (or future dates within 3 months from today's date only if the user did not specify dates), limit to 4 results.
- Ask for any details you don't know, like origin and destination, etc.
- You must generate a non-empty JSON response if the user provides origin and destination location.
- Current time: {_time?}
- Context user profile: {user_profile?}
- Context origin: {origin?} and destination: {destination?}

IMPORTANT — Canonical Schedule for San Francisco (SFO) <-> Cusco (CUZ):
When the user searches for flights between San Francisco (SFO) and Cusco (CUZ) (e.g. May 10, 2027 to May 14, 2027), ALWAYS return these exact 4 flights so all downstream seat, itinerary, booking, and monitoring agents share identical flight numbers, times, and prices:
1. Outbound Recommended: flight_number "LA2405", airlines ["LATAM Airlines"], departure {{"city_name": "San Francisco", "airport_code": "SFO", "timestamp": "2027-05-10T08:30:00"}}, arrival {{"city_name": "Cusco", "airport_code": "CUZ", "timestamp": "2027-05-10T19:45:00"}}, price_in_usd: 650, number_of_stops: 1 (via Lima LIM)
2. Return Recommended: flight_number "LA2406", airlines ["LATAM Airlines"], departure {{"city_name": "Cusco", "airport_code": "CUZ", "timestamp": "2027-05-14T11:15:00"}}, arrival {{"city_name": "San Francisco", "airport_code": "SFO", "timestamp": "2027-05-14T22:30:00"}}, price_in_usd: 650, number_of_stops: 1 (via Lima LIM)
3. Outbound Alternative: flight_number "CM491", airlines ["Copa Airlines"], departure {{"city_name": "San Francisco", "airport_code": "SFO", "timestamp": "2027-05-10T06:15:00"}}, arrival {{"city_name": "Cusco", "airport_code": "CUZ", "timestamp": "2027-05-10T18:50:00"}}, price_in_usd: 690, number_of_stops: 1 (via Panama City PTY)
4. Outbound Alternative: flight_number "AV815", airlines ["Avianca"], departure {{"city_name": "San Francisco", "airport_code": "SFO", "timestamp": "2027-05-10T07:00:00"}}, arrival {{"city_name": "Cusco", "airport_code": "CUZ", "timestamp": "2027-05-10T20:15:00"}}, price_in_usd: 620, number_of_stops: 1 (via Bogota BOG)

Return the response as a JSON object formatted like this:
{{
  "flights": [
    {{
      "flight_number": "Unique identifier for the flight, like LA2405, LA2406, etc.",
      "departure": {{
        "city_name": "Name of the departure city",
        "airport_code": "IATA code of the departure airport",
        "timestamp": "ISO 8601 departure date and time"
      }},
      "arrival": {{
        "city_name": "Name of the arrival city",
        "airport_code": "IATA code of the arrival airport",
        "timestamp": "ISO 8601 arrival date and time"
      }},
      "airlines": [
        "Airline names, e.g., LATAM Airlines"
      ],
      "airline_logo": "/images/airplane.png",
      "price_in_usd": 650,
      "number_of_stops": 1
    }}
  ]
}}
"""

root_agent = Agent(
    model=MODEL,
    name="flight_search_agent",
    include_contents="none",
    description="Help users find best flight deals between an origin and destination.",
    instruction=FLIGHT_SEARCH_INSTR,
    output_schema=FlightsSelection,
    output_key="flight",
    generate_content_config=json_response_config,
)


from google.adk.apps.app import App
from flight_search_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
)
