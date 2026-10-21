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


def ensure_default_state(callback_context: CallbackContext) -> None:
    """Populates default session state keys in VertexAiSessionService before prompt interpolation."""
    state = callback_context.state
    if "_time" not in state:
        state["_time"] = datetime.now().isoformat()
    for key, default_val in DEFAULT_STATE_KEYS.items():
        if key not in state:
            state[key] = default_val


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


def _remove_tools_from_request(llm_request, tool_names: set[str]) -> None:
    """Physically strips specified tool declarations from `llm_request.config.tools`
    so the LLM does not invoke them on the upcoming model turn, while keeping
    `llm_request.tools_dict` intact so ADK never raises Tool not found.
    """
    if not tool_names:
        return
    if getattr(llm_request, "config", None) and getattr(llm_request.config, "tools", None):
        kept_tools = []
        for t in llm_request.config.tools:
            if getattr(t, "function_declarations", None):
                t.function_declarations = [
                    d for d in t.function_declarations if d.name not in tool_names
                ]
                if t.function_declarations:
                    kept_tools.append(t)
            else:
                kept_tools.append(t)
        llm_request.config.tools = kept_tools or None
        if not kept_tools:
            llm_request.config.tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")
            )


def gate_redundant_tools(callback_context: CallbackContext, llm_request):
    """ADK `before_model_callback` that structurally prevents duplicate
    `discover_agents` turns and redundant multi-turn `save_preference` / `memorize`
    loops, and returns specialist A2A agent responses directly from `root_agent`
    without lossy re-summarization.
    """
    from google.adk.models.llm_response import LlmResponse

    agent_name = getattr(callback_context, "agent_name", "") or ""
    contents = getattr(llm_request, "contents", None) or []

    called_in_current_turn: set[str] = set()
    call_agent_replies: list[str] = []
    for content in reversed(contents):
        parts = getattr(content, "parts", None) or []
        has_fn_resp = any(getattr(p, "function_response", None) for p in parts)
        if getattr(content, "role", "") == "user" and not has_fn_resp:
            break
        for p in parts:
            fr = getattr(p, "function_response", None)
            if fr and getattr(fr, "name", None):
                called_in_current_turn.add(fr.name)
                if fr.name == "call_agent" and isinstance(getattr(fr, "response", None), dict):
                    res_text = str(fr.response.get("result") or "").strip()
                    if len(res_text) >= 80 and not res_text.startswith("A2A request failed"):
                        call_agent_replies.append(res_text)
            fc = getattr(p, "function_call", None)
            if fc and getattr(fc, "name", None):
                called_in_current_turn.add(fc.name)

    if agent_name == "root_agent" and call_agent_replies:
        combined_reply = "\n\n".join(dict.fromkeys(reversed(call_agent_replies)))
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=combined_reply)],
            )
        )

    tools_to_strip: set[str] = set()

    if agent_name in ("inspiration_agent", "planning_agent", "in_trip_agent"):
        tools_to_strip.update({"save_preference", "recall_preferences", "discover_agents"})

    if agent_name == "root_agent" and os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() not in ("1", "true", "yes"):
        tools_to_strip.add("discover_agents")

    if agent_name in ("inspiration_agent", "planning_agent"):
        tools_to_strip.add("memorize")

    if "discover_agents" in called_in_current_turn:
        tools_to_strip.add("discover_agents")

    if called_in_current_turn & {"memorize", "save_preference", "recall_preferences"}:
        tools_to_strip.update({"memorize", "save_preference", "recall_preferences"})

    if agent_name == "root_agent" and "call_agent" in called_in_current_turn:
        tools_to_strip.update({"call_agent", "memorize", "save_preference", "recall_preferences", "discover_agents"})

    _remove_tools_from_request(llm_request, tools_to_strip)
    return None

