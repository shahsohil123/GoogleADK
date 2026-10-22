"""Session state initialization and shared Vertex AI Memory Bank tools (`memorize`,
`recall_preferences`, `save_preference`) for ADK agents.
"""

import os
from datetime import datetime
from google.adk.agents.callback_context import CallbackContext
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types

DEFAULT_USER_PROFILE = {
    "passport_nationality": "US Citizen",
    "seat_preference": "",
    "food_preference": "",
    "allergies": [],
    "likes": [],
    "dislikes": [],
    "price_sensitivity": [],
    "home": {
        "event_type": "home",
        "address": "",
        "local_prefer_mode": "drive",
    },
}

DEFAULT_STATE_KEYS = {
    "user_profile": DEFAULT_USER_PROFILE,
    "itinerary": {},
    "origin": "",
    "destination": "",
    "start_date": "",
    "end_date": "",
    "outbound_flight_selection": "",
    "outbound_seat_number": "",
    "return_flight_selection": "",
    "return_seat_number": "",
    "hotel_selection": "",
    "room_selection": "",
    "poi": "",
    "flight": "",
    "hotel": "",
    "itinerary_datetime": "",
    "itinerary_start_date": "",
    "itinerary_end_date": "",
}



async def memorize(key: str, value: str, tool_context: ToolContext) -> dict:
    """Memorize a key-value pair in Vertex AI Session Service (`state`) so the session
    tracks trip selections and profile state without triggering redundant LLM consolidation calls.

    Args:
        key: The label indexing the memory to store the value (e.g. "origin", "destination", "itinerary", "food_preference").
        value: The information to be stored.
    """
    tool_context.state[key] = value
    return {"status": f'Stored "{key}": "{value}" in shared Vertex AI Session state'}


async def recall_preferences(query: str, tool_context: ToolContext) -> dict:
    """Search the shared Vertex AI Memory Bank for facts, preferences, or trip selections saved across any agent.

    Args:
        query: What to search for in the shared Memory Bank (e.g. "dietary preferences", "itinerary destination flights").
    """
    try:
        result = await tool_context.search_memory(query)
    except ValueError:
        return {"known": False, "reason": "Memory Bank is not configured for this session."}

    facts = [
        part.text
        for memory in result.memories
        for part in (memory.content.parts or [])
        if part.text
    ]
    if not facts:
        return {"known": False, "facts": []}
    return {"known": True, "facts": facts}


async def save_preference(fact: str, tool_context: ToolContext) -> dict:
    """Persist a single fact or preference to the shared Vertex AI Memory Bank.

    Args:
        fact: One self-contained fact or preference to store across sessions and agents.
    """
    try:
        await tool_context.add_memory(
            memories=[MemoryEntry(content=types.Content(role="user", parts=[types.Part(text=fact)]))],
            custom_metadata={"enable_consolidation": False},
        )
    except ValueError:
        return {"saved": False, "reason": "Memory Bank is not configured for this session."}
    return {"saved": True, "fact": fact}


recall_preferences_tool = FunctionTool(recall_preferences)
save_preference_tool = FunctionTool(save_preference)
