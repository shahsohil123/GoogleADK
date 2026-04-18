"""
Custom tools for the Travel Concierge agents.

Includes human-in-the-loop approval tools and long-running workflow controls.
"""

import json
from pathlib import Path

from google.adk.tools import FunctionTool, ToolContext

RESOURCES_DIR = Path(__file__).parent.parent / "resources"


# ---------------------------------------------------------------------------
# File reading tools for preferences agent
# ---------------------------------------------------------------------------

async def read_user_profile() -> dict:
    """Read the traveler's profile including dietary preferences, travel style, and interests.

    Returns the contents of user_profile.md from the resources folder.
    """
    profile_file = RESOURCES_DIR / "user_profile.md"
    if not profile_file.exists():
        return {"error": "user_profile.md not found"}
    return {"content": profile_file.read_text()}


async def read_past_trips() -> dict:
    """Read the traveler's past trip history and what they loved/didn't love.

    Returns the contents of past_trips.md from the resources folder.
    """
    trips_file = RESOURCES_DIR / "past_trips.md"
    if not trips_file.exists():
        return {"error": "past_trips.md not found"}
    return {"content": trips_file.read_text()}


# ---------------------------------------------------------------------------
# Human-in-the-loop: Day approval (requires confirmation before proceeding)
# ---------------------------------------------------------------------------

async def record_day_approval(
    day_number: int,
    tool_context: ToolContext,
) -> dict:
    """Record that the user approved a day's itinerary (call after user says 'approve' or 'sounds good').

    Args:
        day_number: Which day was approved (1, 2, 3, etc.).
    """
    approved_days = tool_context.state.get("approved_days", [])
    approved_days.append({
        "day": day_number,
        "status": "approved",
    })
    tool_context.state["approved_days"] = approved_days
    tool_context.state["current_day"] = day_number + 1

    return {
        "status": "approved",
        "message": f"Day {day_number} recorded as approved. Ready to plan day {day_number + 1}.",
    }


# NO confirmation required — user will say "approve" in chat
approve_day_tool = FunctionTool(record_day_approval)


# ---------------------------------------------------------------------------
# Human-in-the-loop: Final booking confirmation
# ---------------------------------------------------------------------------

async def record_final_booking(
    destination: str,
    total_days: int,
    total_estimated_cost: str,
    tool_context: ToolContext,
) -> dict:
    """Record the final booking confirmation (call after user approves the full itinerary).

    Args:
        destination: The trip destination (e.g., "Tokyo, Japan").
        total_days: Total number of days in the trip.
        total_estimated_cost: Total estimated cost for the entire trip.
    """
    tool_context.state["booking_confirmed"] = True
    tool_context.state["final_itinerary"] = {
        "destination": destination,
        "days": total_days,
        "cost": total_estimated_cost,
    }

    return {
        "status": "booked",
        "message": f"✅ Trip to {destination} for {total_days} days confirmed! Total: {total_estimated_cost}",
        "confirmation_id": "DEMO-" + destination.upper().replace(" ", "")[:6] + "-2026",
    }


confirm_booking_tool = FunctionTool(record_final_booking)


# ---------------------------------------------------------------------------
# Long-running workflow: Pause and resume controls
# ---------------------------------------------------------------------------

async def pause_for_human_input(
    reason: str,
    question_for_human: str,
    options: str,
    tool_context: ToolContext,
) -> dict:
    """Pause the planning process and wait for human input before continuing.

    Use this when you need the human's preference or decision to continue planning.
    The workflow will stop here and resume when the human responds.

    Args:
        reason: Why we're pausing (e.g., "Need preference for hotel style").
        question_for_human: The specific question to ask the human.
        options: Suggested options for the human (e.g., "A) Boutique hotel, B) Ryokan, C) Airbnb").
    """
    tool_context.state["workflow_paused"] = True
    tool_context.state["pause_reason"] = reason
    tool_context.state["pending_question"] = question_for_human

    return {
        "status": "paused",
        "message": f"Workflow paused: {reason}",
        "question": question_for_human,
        "options": options,
        "instruction": "Please respond with your choice to resume planning.",
    }


pause_tool = FunctionTool(pause_for_human_input)


async def save_itinerary_to_file(
    destination: str,
    itinerary_content: str,
    tool_context: ToolContext,
) -> dict:
    """Save the final approved itinerary to a file in the resources folder.

    Args:
        destination: Trip destination for the filename.
        itinerary_content: The complete itinerary text to save.
    """
    filename = f"itinerary_{destination.lower().replace(' ', '_').replace(',', '')}.md"
    filepath = RESOURCES_DIR / filename
    filepath.write_text(itinerary_content)

    return {
        "status": "saved",
        "file": filename,
        "path": str(filepath),
    }


save_itinerary_tool = FunctionTool(save_itinerary_to_file)


# Wrap file-reading tools
profile_tool = FunctionTool(read_user_profile)
trips_tool = FunctionTool(read_past_trips)
