"""Pydantic schemas for flight_search_agent."""

from google.genai import types
from pydantic import BaseModel, Field

json_response_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
)


class AirportEvent(BaseModel):
    city_name: str = Field(description="Name of the departure/arrival city")
    airport_code: str = Field(description="IATA code of the airport")
    timestamp: str = Field(description="ISO 8601 departure or arrival date and time")


class Flight(BaseModel):
    flight_number: str = Field(description="Unique identifier for the flight, like BA123, AA31.")
    departure: AirportEvent
    arrival: AirportEvent
    airlines: list[str] = Field(description="Airline names, e.g., American Airlines, Emirates")
    airline_logo: str = Field(description="Airline logo location")
    price_in_usd: int = Field(description="Flight price in US dollars")
    number_of_stops: int = Field(description="Number of stops during the flight")


class FlightsSelection(BaseModel):
    flights: list[Flight]
