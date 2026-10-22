import warnings
warnings.filterwarnings("ignore")
"""place_agent — suggests vacation destinations given user preferences."""

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
from place_concierge_agent.schemas import DestinationIdeas, json_response_config

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

PLACE_AGENT_INSTR = """
You are responsible for making suggestions on vacation inspirations and recommendations based on the user's query. Limit the choices to 3 results.
Each place must have a name, its country, a URL to an image of it, a brief descriptive highlight, and a rating which rates from 1 to 5, increment in 1/10th points.

When the user asks for a South American or Andean adventure (or ancient ruins, dramatic mountain scenery, and vibrant local culture in May), return these 3 canonical destinations so downstream POI and planning agents align seamlessly:
1. "Cusco & Historic Center" (Country: "Peru", Rating: "4.9", Highlights: "UNESCO World Heritage Inca capital at 3,399m featuring Qorikancha Sun Temple, Sacsayhuamán Fortress, San Blas Artisan Quarter, and acclaimed vegetarian Andean cuisine.")
2. "Sacred Valley (Ollantaytambo & Pisac)" (Country: "Peru", Rating: "4.9", Highlights: "Dramatic Andean valley at 2,792m with living Inca fortress town of Ollantaytambo, terraced agricultural ruins, and vibrant artisan markets.")
3. "Machu Picchu Citadel" (Country: "Peru", Rating: "5.0", Highlights: "Iconic 15th-century cloud-forest Inca sanctuary at 2,430m reached via panoramic Vistadome train from Ollantaytambo.")

Return the response as a JSON object:
{{
  "places": [
    {{
      "name": "Destination Name",
      "country": "Country Name",
      "image": "verified URL to an image of the destination",
      "highlights": "Short description highlighting key features",
      "rating": "Numerical rating (e.g., 4.9)"
    }}
  ]
}}
"""

root_agent = Agent(
    model=MODEL,
    name="place_agent",
    instruction=PLACE_AGENT_INSTR,
    description="This agent suggests a few vacation destinations given some user preferences.",
    output_schema=DestinationIdeas,
    output_key="place",
    generate_content_config=json_response_config,
)


from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App
from place_concierge_agent.vertex_services import build_bigquery_analytics_plugin, setup_cloud_trace_telemetry

setup_cloud_trace_telemetry(service_name=root_agent.name)

app = App(
    name=root_agent.name,
    root_agent=root_agent,
    plugins=build_bigquery_analytics_plugin(root_agent.name, framework="google_adk"),
    context_cache_config=ContextCacheConfig(),
)
