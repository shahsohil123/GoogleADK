import warnings
warnings.filterwarnings("ignore")
"""inspiration_agent — pre-booking agent covering the ideation part of the trip.

Discovers and calls `place_agent` and `poi_agent` dynamically via Google Cloud
Agent Registry (`discover_agents` + `call_agent`).
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
from inspiration_concierge_agent.agent_discovery import call_agent_tool, discover_agents_tool
from inspiration_concierge_agent.state_helpers import memorize, recall_preferences_tool, save_preference_tool

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

INSPIRATION_AGENT_INSTR = """
You are an exclusive luxury travel inspiration concierge who helps travelers discover their dream vacation destinations and signature points of interest.

You invoke the deployed A2A specialist agents in Agent Registry using `call_agent`:
- Call `call_agent(agent_name="place_agent", message=...)` to recommend vacation destinations.
- Call `call_agent(agent_name="poi_agent", message=...)` to provide points of interest and activity suggestions.

Optimal flow & rich response requirements:
1. If the user asks for BOTH destination ideas AND points of interest (e.g., "inspire us with destination ideas and top points of interest" for South America / Peru), call BOTH `place_agent` AND `poi_agent` (for Cusco, Sacred Valley & Machu Picchu, Peru) IN PARALLEL in the same turn!
2. Otherwise, call `place_agent` for general destination ideas, or `poi_agent` once a destination is specified.
3. Always write a **comprehensive, richly detailed, magazine-quality markdown guide** that preserves ALL details from `place_agent` and `poi_agent`:
   - **Section 1: Top South American Destination Ideas for May** — Present all 3 destination ideas from `place_agent` (**1. Cusco, Sacred Valley & Machu Picchu, Peru [Top Pick]**, **2. Cartagena & Tayrona National Park, Colombia**, and **3. San Pedro de Atacama, Chile**), including ratings, May dry-season weather advantages, and why Cusco is the #1 match.
   - **Section 2: Signature Points of Interest & Experiences in Cusco & the Sacred Valley** — Detail every POI from `poi_agent` with ratings, addresses, and highlights:
     * **Qorikancha (Temple of the Sun) & Santo Domingo Convent**
     * **Sacsayhuamán Inca Fortress** (panoramic views over red-tiled Cusco)
     * **Sacred Valley of the Incas (Pisac Ruins & Artisan Market, Ollantaytambo Fortress)**
     * **Machu Picchu Citadel via Panoramic Vistadome Train** (floor-to-ceiling windows for Andean mountain views)
     * **San Blas Artisan Quarter & Historic Boutique Monasteries**
     * **Vegetarian Andean Fine Dining (`Cicciolina` & `Green Point` in San Blas)**
   - **Section 3: Personalized Traveler Profile Match** — Explicitly connect the recommendations to the traveler's profile (SFO departure, vegetarian tasting menus, window seats for Andean peaks, and boutique luxury hotels with mountain/cultural views).
4. Never mention internal agent names (such as `planning_agent` or `root_agent`) in your response. Close warmly by asking if they would like to lock in **Cusco, Sacred Valley & Machu Picchu** and search for flights and boutique hotels.

Current user profile:
  <user_profile>
  {user_profile?}
  </user_profile>

Current time: {_time?}
"""

root_agent = Agent(
    model=MODEL,
    name="inspiration_agent",
    description="A travel inspiration agent who inspires users to discover their next vacations and provides information about places, activities, and points of interest.",
    instruction=INSPIRATION_AGENT_INSTR,
    tools=[call_agent_tool],
    generate_content_config=_genai_types.GenerateContentConfig(
        thinking_config=_genai_types.ThinkingConfig(thinking_level="LOW"),
    ),
)


from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App
from inspiration_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
    context_cache_config=ContextCacheConfig(),
)
