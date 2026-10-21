"""Session state initialization and shared Vertex AI Memory Bank tools (`memorize`,
`recall_preferences`, `save_preference`) for ADK agents.
"""

from datetime import datetime
from google.adk.agents.callback_context import CallbackContext

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

