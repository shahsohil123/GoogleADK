"""Pydantic schemas for poi_agent."""

from google.genai import types
from pydantic import BaseModel, Field

json_response_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
)


class POI(BaseModel):
    place_name: str = Field(description="Name of the attraction")
    address: str = Field(description="An address or sufficient information to geocode for a Lat/Lon")
    lat: str = Field(description="Numerical representation of Latitude of the location (e.g., 20.6843)")
    long: str = Field(description="Numerical representation of Longitude of the location (e.g., -88.5678)")
    review_ratings: str = Field(description="Numerical representation of rating (e.g. 4.8)")
    highlights: str = Field(description="Short description highlighting key features")
    image_url: str = Field(description="Verified URL to an image of the destination")
    map_url: str | None = Field(default=None, description="Verified URL to Google Map")
    place_id: str | None = Field(default=None, description="Google Map place_id")


class POISuggestions(BaseModel):
    places: list[POI]
