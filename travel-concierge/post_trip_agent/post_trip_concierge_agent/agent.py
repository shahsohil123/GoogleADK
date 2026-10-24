import warnings
warnings.filterwarnings("ignore")
"""post_trip_agent — post-booking agent covering the user experience after the trip."""

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
from post_trip_concierge_agent.state_helpers import memorize, recall_preferences_tool, save_preference_tool

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

POSTTRIP_INSTR = """
You are a post-trip travel assistant. Based on the user's request and any provided trip information (`{itinerary?}`), assist the user with post-trip matters and store their learned travel preferences into the shared Memory Bank.

If no itinerary or trip experience is shared yet, ask the traveler about their recent trip or let them know you can help once there is an itinerary.

When the user shares their post-trip feedback or preferences (such as seating preferences like window seats, lodging preferences like boutique historic luxury hotels with oxygen-enriched rooms at high altitude, dietary preferences, or activity preferences like private early-morning archaeological tours):
- Batch ALL `save_preference` and `memorize` tool calls IN PARALLEL in a single turn!
- Confirm all stored preferences clearly and thank the user, noting that this feedback is saved in Memory Bank for their future trips.
"""

root_agent = Agent(
    model=MODEL,
    name="post_trip_agent",
    include_contents="none",
    description="A follow-up post-trip agent to learn from the user's travel experience and store preferences for future trips.",
    instruction=POSTTRIP_INSTR,
    tools=[memorize, recall_preferences_tool, save_preference_tool],
    generate_content_config=_genai_types.GenerateContentConfig(
        thinking_config=_genai_types.ThinkingConfig(thinking_level="LOW"),
    ),
)


from google.adk.apps.app import App
from post_trip_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
)
