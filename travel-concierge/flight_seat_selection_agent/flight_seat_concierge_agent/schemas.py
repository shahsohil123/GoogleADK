"""Pydantic schemas for flight_seat_selection_agent."""

from google.genai import types
from pydantic import BaseModel, Field

json_response_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
)


class Seat(BaseModel):
    is_available: bool = Field(description="Whether the seat is available for selection.")
    price_in_usd: int = Field(description="The cost of the seat selection.")
    seat_number: str = Field(description="Seat number, e.g. 22A, 34F.")


class SeatsSelection(BaseModel):
    seats: list[list[Seat]]
