"""Preference memory tools, backed by ADK's Memory Bank service.

Unlike travel_concierge's `preferences_reader` (which reads a static local
profile file), this agent's preferences live in Vertex AI Agent Engine's
Memory Bank — scoped per `user_id` and persisted across sessions — so a
returning user doesn't need to restate their preferences, and a new user
gets asked for them.
"""

from google.adk.memory.memory_entry import MemoryEntry
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types


async def recall_preferences(query: str, tool_context: ToolContext) -> dict:
    """Look up what's already known about this user's travel preferences.

    Call this first, before researching a destination. Search for dietary
    restrictions, food interests, and the kinds of attractions they enjoy
    (e.g. "dietary restrictions, food interests, favorite attraction types").

    Args:
        query: What to search for in the user's remembered preferences.
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
    """Persist a single fact the user stated about their travel preferences.

    Call this as soon as the user tells you something durable — a dietary
    restriction, a food they love or avoid, or a type of attraction they
    enjoy or dislike — so future trips don't need to ask again.

    Args:
        fact: One self-contained preference, e.g. "Vegetarian, no strict
            allergies" or "Prefers museums and history over nightlife".
    """
    try:
        await tool_context.add_memory(
            memories=[MemoryEntry(content=types.Content(role="user", parts=[types.Part(text=fact)]))],
            custom_metadata={"enable_consolidation": True},
        )
    except ValueError:
        return {"saved": False, "reason": "Memory Bank is not configured for this session."}
    return {"saved": True, "fact": fact}


recall_preferences_tool = FunctionTool(recall_preferences)
save_preference_tool = FunctionTool(save_preference)
