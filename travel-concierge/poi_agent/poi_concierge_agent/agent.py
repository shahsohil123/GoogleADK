import warnings
warnings.filterwarnings("ignore")
"""poi_agent — suggests activities and points of interest given a destination."""

import logging
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
from poi_concierge_agent.schemas import POISuggestions, json_response_config

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
MAPS_MCP_URL = "https://mapstools.googleapis.com/mcp"


def _get_places_toolset():
    maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not maps_api_key:
        return []
    try:
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

        return [
            McpToolset(
                connection_params=StreamableHTTPConnectionParams(
                    url=MAPS_MCP_URL,
                    headers={
                        "X-Goog-Api-Key": maps_api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                ),
                errlog=None,
            )
        ]
    except Exception:
        return []


POI_AGENT_INSTR = """
You are responsible for providing a list of point of interests, things to do recommendations based on the user's destination choice. Limit the choices to 5 results.

When the destination involves Cusco, the Sacred Valley, Machu Picchu, or Peru, return these 5 canonical points of interest:
1. "Machu Picchu Citadel" (Address: "Aguas Calientes, Urubamba Province 08680, Peru", lat: "-13.1631", long: "-72.5450", review_ratings: "5.0", highlights: "Iconic 15th-century Inca citadel perched at 2,430m in the Andean cloud forest, accessed via panoramic Vistadome train from Ollantaytambo.")
2. "Qorikancha (Temple of the Sun)" (Address: "Calle Santo Domingo s/n, Av. El Sol, Cusco 08002, Peru", lat: "-13.5202", long: "-71.9754", review_ratings: "4.9", highlights: "The Inca Empire's most sacred Sun Temple featuring precision mortarless imperial stonework in the heart of Cusco.")
3. "Sacsayhuamán Fortress" (Address: "Cuesta del Socorro, Cusco 08002, Peru", lat: "-13.5078", long: "-71.9817", review_ratings: "4.9", highlights: "Monumental Inca ceremonial fortress overlooking Cusco with zigzagging cyclopean limestone walls and panoramic mountain views.")
4. "Sacred Valley: Ollantaytambo Fortress & Pisac Ruins" (Address: "Ollantaytambo 08676, Sacred Valley, Peru", lat: "-13.2584", long: "-72.2633", review_ratings: "4.9", highlights: "Living Inca grid town, agricultural terraces, Temple of the Sun ruins, and vibrant Pisac artisan market.")
5. "San Blas Artisan Quarter & Plaza de Armas" (Address: "Plazoleta San Blas, Historic Center, Cusco 08003, Peru", lat: "-13.5150", long: "-71.9758", review_ratings: "4.8", highlights: "Bohemian cobblestone neighborhood with twelve-angled Inca stone walls, galleries, and top vegetarian dining at Green Point and Cicciolina.")

Return the response as a JSON object:
{{
 "places": [
    {{
      "place_name": "Name of the attraction",
      "address": "An address or sufficient information to geocode for a Lat/Lon",
      "lat": "Numerical representation of Latitude of the location (e.g., -13.1631)",
      "long": "Numerical representation of Longitude of the location (e.g., -72.5450)",
      "review_ratings": "Numerical representation of rating (e.g. 4.9, 5.0)",
      "highlights": "Short description highlighting key features",
      "image_url": "The `photosUrl` field from Google Maps Grounding Lite response for the place",
      "map_url": "The `placeUrl` field from Google Maps Grounding Lite response for the place",
      "place_id": "The `id` field from Google Maps Grounding Lite response for the place"
    }}
  ]
}}
"""

root_agent = Agent(
    model=MODEL,
    name="poi_agent",
    include_contents="none",
    description="This agent suggests a few activities and points of interests given a destination.",
    instruction=POI_AGENT_INSTR,
    output_schema=POISuggestions,
    output_key="poi",
    generate_content_config=json_response_config,
    tools=_get_places_toolset(),
)


from google.adk.apps.app import App
from poi_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
)
