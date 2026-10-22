"""Google Search Grounding and shared Vertex AI Memory Bank tools for the
CrewAI `pre_trip_agent`.
"""

import os

from crewai.tools import tool
from google import genai
from google.genai import types

from pre_trip_crewai_agent.vertex_services import (
    save_memory_fact_sync,
    search_memory_facts_sync,
)


_GENAI_HTTP_OPTS = types.HttpOptions(
    retry_options=types.HttpRetryOptions(
        attempts=5,
        initial_delay=2.0,
        max_delay=30.0,
        exp_base=2.0,
        http_status_codes=[429, 500, 502, 503, 504],
    )
)
_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEXAI_PROJECT")
_GENAI_CLIENT = (
    genai.Client(
        vertexai=True,
        project=_PROJECT,
        location="global",
        http_options=_GENAI_HTTP_OPTS,
    )
    if _PROJECT
    else genai.Client(http_options=_GENAI_HTTP_OPTS)
)


@tool("google_search_grounding")
def google_search_grounding(query: str) -> str:
    """Search Google for up-to-date travel information (visa requirements, medical requirements, storm monitor, travel advisories) and return a concise, actionable answer for a traveler."""
    model = os.environ.get("GENAI_MODEL", "gemini-3-flash-preview")

    response = _GENAI_CLIENT.models.generate_content(
        model=model,
        contents=(
            "Answer the traveler's question directly using Google Search grounding; "
            "provide a brief, concise, and immediately actionable summary.\n\n"
            f"Query: {query}"
        ),
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        ),
    )
    return response.text or "No current updates found."


@tool("recall_shared_memory")
def recall_shared_memory(query: str) -> str:
    """Search the shared Vertex AI Memory Bank for the traveler's itinerary, nationality, dietary preferences, or trip details."""
    try:
        facts = search_memory_facts_sync(query)
        return "\n".join(f"- {f}" for f in facts) if facts else "No stored memories found."
    except Exception as exc:
        return f"Memory lookup unavailable: {exc}"


@tool("save_shared_memory")
def save_shared_memory(fact: str) -> str:
    """Save a pre-trip packing list or travel readiness fact into the shared Vertex AI Memory Bank."""
    try:
        save_memory_fact_sync(fact)
        return f"Saved to shared Vertex AI Memory Bank: {fact}"
    except Exception as exc:
        return f"Failed to save to Memory Bank: {exc}"
