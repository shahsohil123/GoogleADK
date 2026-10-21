"""Tools for the LangGraph booking_agent, backed by the shared Vertex AI
Session Service and Vertex AI Memory Bank.
"""

from datetime import datetime, timezone
import uuid

from langchain_core.tools import tool

from booking_langgraph_agent.vertex_services import (
    save_memory_fact_sync,
    search_memory_facts_sync,
)

_RESERVATIONS: dict[str, dict] = {}
_LAST_PAYMENT_METHOD: str | None = None


@tool
def recall_trip_and_payment_memory(query: str) -> dict:
    """Search the shared Vertex AI Memory Bank for the traveler's itinerary, flight/hotel selections, or preferred payment method.

    Args:
        query: What to search for (e.g. "itinerary flights hotels booking" or "preferred payment method").
    """
    try:
        facts = search_memory_facts_sync(query)
        return {"found": bool(facts), "facts": facts}
    except Exception as exc:
        return {"found": False, "facts": [], "error": str(exc)}


@tool
def create_reservation(item_description: str, price_in_usd: float, item_type: str = "travel_item") -> dict:
    """Create a reservation for a flight, hotel, tour, venue, transport, or event that requires booking.

    Args:
        item_description: Human-readable description of the item being reserved.
        price_in_usd: Total price in USD for the reservation (for hotels, multiply per-night rate by number of nights).
        item_type: Category of the item ("flight", "hotel", "visit", "transport", etc.).
    """
    reservation_id = f"RES-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "reservation_id": reservation_id,
        "item_description": item_description,
        "item_type": item_type,
        "price_in_usd": price_in_usd,
        "status": "RESERVED_PENDING_PAYMENT",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "order_id": None,
        "payment_method": None,
    }
    _RESERVATIONS[reservation_id] = record
    try:
        save_memory_fact_sync(
            f"Created reservation {reservation_id} for {item_description} (${price_in_usd:.2f} USD), status: RESERVED_PENDING_PAYMENT."
        )
    except Exception:
        pass
    return {
        **record,
        "message": (
            f"Created reservation {reservation_id} for '{item_description}' "
            f"(${price_in_usd:.2f} USD). Next, call payment_choice to show payment options "
            "and ask the user which payment method they want to use."
        ),
    }


@tool
def payment_choice() -> dict:
    """Return the available payment methods to present to the user before calling process_payment."""
    previous = _LAST_PAYMENT_METHOD
    if not previous:
        try:
            facts = search_memory_facts_sync("preferred payment method")
            if facts:
                previous = facts[0]
        except Exception:
            pass
    return {
        "available_methods": [
            "1. Apple Pay",
            "2. Google Pay",
            "3. Credit Card on file",
        ],
        "previous_choice": previous,
        "instruction": (
            "Present these 3 choices (1. Apple Pay, 2. Google Pay, 3. Credit Card on file) "
            "to the user and wait for them to choose. If previous_choice is set, ask if "
            "they would like to use the same method."
        ),
    }


@tool
def process_payment(reservation_id: str, payment_method: str) -> dict:
    """Execute the payment for a reservation using the user's selected payment method.

    Payment Gateway simulation scenarios:
    - Scenario 1: If the user selects Apple Pay, the transaction is DECLINED.
    - Scenario 2: If the user selects Google Pay, the transaction is APPROVED.
    - Scenario 3: If the user selects Credit Card, the transaction is APPROVED.

    Args:
        reservation_id: The reservation_id returned by create_reservation.
        payment_method: The payment method selected by the user ("Apple Pay", "Google Pay", or "Credit Card on file").
    """
    global _LAST_PAYMENT_METHOD
    _LAST_PAYMENT_METHOD = payment_method

    res = _RESERVATIONS.get(reservation_id)
    normalized = payment_method.strip().lower()

    if "apple" in normalized:
        if res:
            res["status"] = "PAYMENT_DECLINED"
            res["payment_method"] = "Apple Pay"
        return {
            "reservation_id": reservation_id,
            "payment_method": "Apple Pay",
            "status": "DECLINED",
            "order_id": None,
            "message": (
                "Transaction DECLINED by Payment Gateway for Apple Pay. "
                "Please ask the user to choose another payment method (Google Pay or Credit Card on file)."
            ),
        }

    approved_method = "Google Pay" if "google" in normalized else "Credit Card on file"
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    if res:
        res["status"] = "CONFIRMED_AND_PAID"
        res["payment_method"] = approved_method
        res["order_id"] = order_id

    try:
        save_memory_fact_sync(
            f"Traveler paid for reservation {reservation_id} ({res['item_description'] if res else 'booking'}) "
            f"using preferred payment method {approved_method}. Confirmed Order ID: {order_id}."
        )
    except Exception:
        pass

    return {
        "reservation_id": reservation_id,
        "payment_method": approved_method,
        "status": "APPROVED",
        "order_id": order_id,
        "item_description": res["item_description"] if res else None,
        "price_in_usd": res["price_in_usd"] if res else None,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "message": f"Payment APPROVED via {approved_method}. Final Order ID: {order_id}. Booking confirmed.",
    }


@tool
def list_reservations() -> dict:
    """List all reservations and their payment/order status."""
    return {
        "count": len(_RESERVATIONS),
        "reservations": list(_RESERVATIONS.values()),
    }


ALL_TOOLS = [
    recall_trip_and_payment_memory,
    create_reservation,
    payment_choice,
    process_payment,
    list_reservations,
]
