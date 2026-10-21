"""Pydantic schemas for hotel_room_selection_agent."""

from google.genai import types
from pydantic import BaseModel, Field

json_response_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
)


class Room(BaseModel):
    is_available: bool = Field(description="Whether the room type is available for selection.")
    price_in_usd: int = Field(description="The cost of the room selection.")
    room_type: str = Field(description="Type of room, e.g. Twin with Balcony, King with Ocean View.")


class RoomsSelection(BaseModel):
    rooms: list[Room]
