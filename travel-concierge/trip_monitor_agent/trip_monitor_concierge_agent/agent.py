import warnings
warnings.filterwarnings("ignore")
"""trip_monitor_agent — monitors aspects of an itinerary and flags items needing changes."""

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


def flight_status_check(
    flight_number: str, flight_date: str, checkin_time: str, departure_time: str
) -> dict:
    """Checks the status of a flight, given its flight_number, date, checkin_time and departure_time."""
    return {"status": f"Flight {flight_number} ({flight_date}): ON TIME • Terminal 1"}


def event_booking_check(event_name: str, event_date: str, event_location: str) -> dict:
    """Checks the status of an event that requires booking, given its event_name, date, and event_location."""
    if event_name.startswith("Space Needle"):
        return {"status": f"{event_name} is closed."}
    return {"status": f"{event_name} ({event_date} at {event_location}): CONFIRMED & OPEN"}


def weather_impact_check(
    activity_name: str, activity_date: str, activity_location: str
) -> dict:
    """Checks the status of an outdoor activity that may be impacted by weather."""
    return {"status": f"{activity_name} ({activity_date} in {activity_location}): Clear Andean dry-season skies (68°F day / 38°F night), no weather disruptions"}


TRIP_MONITOR_INSTR = """
Given the itinerary or flight/trip details in the conversation message or state (`{itinerary?}`) and user profile (`{user_profile?}`):
If neither the message nor `{itinerary?}` mentions any flights, destination, hotel, or trip events at all, inform the caller that an itinerary is required to monitor trip events.

Otherwise (including when the caller mentions arriving in Cusco or asks to check flights for Cusco / Belmond Hotel Monasterio), identify the flights, events, and outdoor activities (for Cusco trips, default to LATAM flights `LA2405` on `2027-05-10` and `LA2406` on `2027-05-14` if specific flight numbers were not passed) and check their status using your tools in parallel:
- Flights delays or cancellations -> use `flight_status_check`
- Events that require booking -> use `event_booking_check`
- Outdoor activities affected by weather -> use `weather_impact_check`

Summarize the live status clearly and present a short list of suggested changes (if any) for the user's attention.
"""

root_agent = Agent(
    model=MODEL,
    name="trip_monitor_agent",
    include_contents="none",
    description="Monitor aspects of an itinerary (flights, event bookings, weather impacts) and bring attention to items that necessitate changes.",
    instruction=TRIP_MONITOR_INSTR,
    tools=[flight_status_check, event_booking_check, weather_impact_check],
    output_key="daily_checks",
    generate_content_config=_genai_types.GenerateContentConfig(
        thinking_config=_genai_types.ThinkingConfig(thinking_level="LOW"),
    ),
)


from google.adk.apps.app import App
from trip_monitor_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
)
