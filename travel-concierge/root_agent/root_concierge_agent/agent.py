import warnings
warnings.filterwarnings("ignore")
"""Root Travel Concierge Orchestrator (`root_agent`).

Discovers and invokes all mid-level specialist A2A agents dynamically at
runtime via Google Cloud Agent Registry (`discover_agents` + `call_agent`):
- `inspiration_agent` (ADK)
- `planning_agent` (ADK)
- `booking_agent` (LangGraph)
- `pre_trip_agent` (CrewAI)
- `in_trip_agent` (ADK)
- `post_trip_agent` (ADK)
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
from google.adk.models.google_llm import Gemini
from google.genai import types
from root_concierge_agent.agent_discovery import call_agent_tool, discover_agents_tool
from root_concierge_agent.state_helpers import memorize, recall_preferences_tool, save_preference_tool

MODEL = Gemini(
    model=os.environ.get("GENAI_MODEL", "gemini-3-flash-preview"),
    retry_options=types.HttpRetryOptions(
        attempts=5,
        initial_delay=2.0,
        max_delay=30.0,
        exp_base=2.0,
        http_status_codes=[429, 500, 502, 503, 504],
    ),
)

ROOT_AGENT_INSTR = """
You are an exclusive Travel Concierge orchestrator agent.
You help users discover their dream vacation, plan flights and hotels, complete bookings and payments, and support them across pre-trip, in-trip, and post-trip phases.

You do not have sub-agents hardcoded locally. Instead, you use `discover_agents(capability)` and `call_agent(agent_name, message)` to dynamically find and invoke specialist A2A agents registered in Google Cloud Agent Registry:
1. `inspiration_agent`: when the user asks about general destination knowledge, vacation inspiration, or things to do / points of interest.
2. `planning_agent`: when the user asks about finding flight deals, seat selection, hotel search, room selection, or building a full multi-day itinerary.
3. `booking_agent` (LangGraph): when the user is ready to reserve flights/hotels/activities, choose a payment method (Apple Pay, Google Pay, Credit Card), or process payments.
4. `pre_trip_agent` (CrewAI): when there is an upcoming itinerary (current date is before `itinerary_start_date`) or the user asks for pre-trip updates (visa, medical, storm alerts, travel advisories, or what to pack).
5. `in_trip_agent`: when the user is currently on the trip (`itinerary_datetime` is between `itinerary_start_date` and `itinerary_end_date`) and needs daily trip monitoring or day-of transit logistics.
6. `post_trip_agent`: when the trip has ended (`itinerary_datetime` is after `itinerary_end_date`) or the user wants to share post-trip feedback and preferences.

When the traveler asks to save their traveler profile or personal travel preferences in memory (such as home airport, dietary preferences, seat preferences, or hotel style) before or during trip planning:
- Call `save_preference` and `memorize` directly to store their traveler profile in the shared Memory Bank and session state (updating `user_profile`, `origin`, `food_preference`, and `seat_preference`), and confirm each saved preference clearly.

IMPORTANT rules when calling remote A2A agents via `call_agent`:
- SPEED OPTIMIZATION: To minimize latency, always invoke multiple independent tools in parallel in a single turn whenever possible (for example, call `save_preference` and `memorize` for all keys at once in a single turn, and if you already know or discovered an agent's resource name in the conversation, call `call_agent` directly without calling `discover_agents` again).
- Always include the relevant trip state (`user_profile`, `itinerary`, `origin`, `destination`, `start_date`, `end_date`, `outbound_flight_selection`, `return_flight_selection`, `hotel_selection`) in the `message` you send to `call_agent`, because each specialist A2A agent runs in its own isolated container!
- When a specialist agent returns a new itinerary or updated selections, save them in your state using `memorize` and reply to the traveler immediately.
- If a specialist agent asks the traveler a follow-up question (such as choosing a flight, seat, hotel, room, or payment method), relay that question to the traveler and pass their reply back to that same `agent_name` on the next turn.

Current user profile:
  <user_profile>
  {user_profile?}
  </user_profile>

Current time: {_time?}
Itinerary datetime override: {itinerary_datetime?}
Itinerary start date: {itinerary_start_date?}
Itinerary end date: {itinerary_end_date?}

Current itinerary:
  <itinerary>
  {itinerary?}
  </itinerary>
"""

root_agent = Agent(
    model=MODEL,
    name="root_agent",
    description="A Travel Concierge orchestrator using multiple independent A2A sub-agents discovered via Google Cloud Agent Registry.",
    instruction=ROOT_AGENT_INSTR,
    tools=[discover_agents_tool, call_agent_tool, memorize, recall_preferences_tool, save_preference_tool],
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    ),
)


from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App
from root_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
    context_cache_config=ContextCacheConfig(),
)
