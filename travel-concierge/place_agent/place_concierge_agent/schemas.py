"""Pydantic schemas for place_agent."""

from google.genai import types
from pydantic import BaseModel, Field

json_response_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
)


class Destination(BaseModel):
    name: str = Field(description="A Destination's Name")
    country: str = Field(description="The Destination's Country Name")
    image: str = Field(description="Verified URL to an image of the destination")
    highlights: str = Field(description="Short description highlighting key features")
    rating: str = Field(description="Numerical rating (e.g., 4.5)")


class DestinationIdeas(BaseModel):
    places: list[Destination]
