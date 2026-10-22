import warnings
warnings.filterwarnings("ignore")
"""in_trip_agent — post-booking agent covering the user experience during the trip.

Discovers and calls `trip_monitor_agent` and `day_of_agent` dynamically via
Google Cloud Agent Registry (`discover_agents` + `call_agent`).
"""

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
from in_trip_concierge_agent.agent_discovery import call_agent_tool, discover_agents_tool
from in_trip_concierge_agent.state_helpers import memorize, recall_preferences_tool, save_preference_tool

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

INTRIP_INSTR = """
You are an in-trip travel concierge providing helpful information during the user's trip:
1. You monitor the user's bookings daily and provide a summary in case changes are needed.
2. You help the user travel from A to B and provide transport and logistical information.
3. By default, you act as a tour guide answering questions about venues and attractions.

You discover and call two specialist A2A agents in Google Cloud Agent Registry via `discover_agents` and `call_agent`:
- When instructed to "monitor" (or check flight/event/weather status), discover and call `trip_monitor_agent`, passing the full itinerary and user_profile in the message.
- When instructed with "transport" (or day-of logistics from A to B), discover and call `day_of_agent`, passing the itinerary, user_profile, and current `itinerary_datetime` in the message.
- When instructed to "memorize" a datetime or value under a key, call `memorize(key, value)`.
- SPEED OPTIMIZATION: Minimize sequential round-trips! If both `trip_monitor_agent` and `day_of_agent` are needed, or multiple `memorize` calls are needed, invoke them IN PARALLEL in the same turn.

Current trip itinerary:
<itinerary>
{itinerary?}
</itinerary>

Current time: "{itinerary_datetime?}" (system time: {_time?})
"""

root_agent = Agent(
    model=MODEL,
    name="in_trip_agent",
    description="Provide in-trip concierge assistance, daily flight/event/weather monitoring, and day-of transit logistics during the tour.",
    instruction=INTRIP_INSTR,
    tools=[call_agent_tool, memorize],
    generate_content_config=_genai_types.GenerateContentConfig(
        thinking_config=_genai_types.ThinkingConfig(thinking_level="LOW"),
    ),
)


from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App
from in_trip_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
    context_cache_config=ContextCacheConfig(),
)
