"""Pydantic schemas for itinerary_agent."""

from google.genai import types
from pydantic import BaseModel, Field

json_response_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(thinking_level="LOW"),
)


class AttractionEvent(BaseModel):
    event_type: str = Field(default="visit")
    description: str = Field(description="A title or description of the activity or attraction visit")
    address: str = Field(description="Full address of the attraction")
    start_time: str = Field(description="Time in HH:MM format, e.g. 09:00")
    end_time: str = Field(description="Time in HH:MM format, e.g. 12:00")
    booking_required: bool = Field(default=False)
    price: str | None = Field(default="", description="Some events may cost money")


class FlightEvent(BaseModel):
    event_type: str = Field(default="flight")
    description: str = Field(description="A title or description of the Flight")
    booking_required: bool = Field(default=True)
    departure_airport: str = Field(description="Airport code, i.e. SEA")
    arrival_airport: str = Field(description="Airport code, i.e. SAN")
    flight_number: str = Field(description="Flight number, e.g. UA5678")
    boarding_time: str = Field(description="Time in HH:MM format, e.g. 15:30")
    seat_number: str = Field(description="Seat Row and Position, e.g. 32A")
    departure_time: str = Field(description="Time in HH:MM format, e.g. 16:00")
    arrival_time: str = Field(description="Time in HH:MM format, e.g. 20:00")
    price: str | None = Field(default="", description="Total air fare")
    booking_id: str | None = Field(default="", description="Booking Reference ID")


class HotelEvent(BaseModel):
    event_type: str = Field(default="hotel")
    description: str = Field(description="A name, title or description of the hotel")
    address: str = Field(description="Full address of the hotel")
    check_in_time: str = Field(description="Time in HH:MM format, e.g. 16:00")
    check_out_time: str = Field(description="Time in HH:MM format, e.g. 11:00")
    room_selection: str = Field(description="Selected room type")
    booking_required: bool = Field(default=True)
    price: str | None = Field(default="", description="Total hotel price including all nights")
    booking_id: str | None = Field(default="", description="Booking Reference ID")


class ItineraryDay(BaseModel):
    day_number: int = Field(description="Which day of the trip this represents, e.g. 1, 2, 3")
    date: str = Field(description="The Date this day in YYYY-MM-DD format")
    events: list[FlightEvent | HotelEvent | AttractionEvent] = Field(
        default_factory=list, description="The list of events for the day"
    )


class Itinerary(BaseModel):
    trip_name: str = Field(description="Simple one liner to describe the trip")
    start_date: str = Field(description="Trip Start Date in YYYY-MM-DD format")
    end_date: str = Field(description="Trip End Date in YYYY-MM-DD format")
    origin: str = Field(description="Trip Origin, e.g. San Diego")
    destination: str = Field(description="Trip Destination, e.g. Seattle")
    days: list[ItineraryDay] = Field(default_factory=list, description="The multi-day itinerary")
