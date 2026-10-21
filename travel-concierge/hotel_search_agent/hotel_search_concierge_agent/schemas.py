"""Pydantic schemas for hotel_search_agent."""

from google.genai import types
from pydantic import BaseModel, Field

json_response_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
)


class Hotel(BaseModel):
    name: str = Field(description="Name of the hotel")
    address: str = Field(description="Full address of the Hotel")
    check_in_time: str = Field(description="Time in HH:MM format, e.g. 16:00")
    check_out_time: str = Field(description="Time in HH:MM format, e.g. 11:00")
    thumbnail: str = Field(description="Hotel logo location")
    price: int = Field(description="Price of the room per night")


class HotelsSelection(BaseModel):
    hotels: list[Hotel]
