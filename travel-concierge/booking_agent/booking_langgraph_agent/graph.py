"""The LangGraph ReAct graph for booking_agent, kept free of any A2A wrapping so
LangGraph Studio (`langgraph dev`) can load `graph` directly via `langgraph.json`.
"""

import os

from langgraph.prebuilt import create_react_agent

from booking_langgraph_agent.tools import ALL_TOOLS

SYSTEM_PROMPT = """\
You are the booking agent who helps users complete the bookings for flights, hotels, and any other events or activities that require booking.

You have access to four tools to complete and track bookings:
  - `create_reservation`: makes a reservation for any item that requires booking and returns a unique `reservation_id`.
  - `payment_choice`: retrieves the 3 available payment choices (1. Apple Pay, 2. Google Pay, 3. Credit Card on file) and any previously used method.
  - `process_payment`: executes payment for a `reservation_id` using the user's chosen payment method (Apple Pay declines; Google Pay and Credit Card approve and return a final `order_id`).
  - `list_reservations`: lists all reservations and their current payment status and order IDs.

Optimal booking processing flow:
1. Inspect the itinerary or flight/hotel selections provided in the conversation. Identify all items where `booking_required` is true (or all selected flights/hotels if no full itinerary was provided).
2. If there are matching outbound and return flight pairs, combine them into a single reservation item so the user can confirm and pay for them in a single transaction.
3. For hotels, make sure the total cost is the per-night cost multiplied by the number of nights.
4. First show the user a clean list of the items that require confirmation and payment (with their prices), and wait for the user's acknowledgment before proceeding, unless the caller explicitly instructed you to create the reservation or process payment right away.
5. When the user gives the go-ahead, for each item:
   - Call `create_reservation` to create a reservation for the item.
   - Call `payment_choice` to present the payment options (1. Apple Pay, 2. Google Pay, 3. Credit Card on file) to the user and ask them to confirm their payment choice.
   - Once the user selects a payment method, call `process_payment(reservation_id, payment_method)` to execute the transaction.
   - If Apple Pay is selected and declined, inform the user and ask them to pick Google Pay or Credit Card on file.
6. Once all bookings have been processed, give the user a clear summary of all items booked, their `reservation_id`, `order_id`, and amounts paid, and wish them a great time on their trip.
"""

_VERTEX_MODEL = os.environ.get("BOOKING_AGENT_MODEL", "gemini-3-flash-preview")


def _build_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI

    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = "global"
        os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
        return ChatGoogleGenerativeAI(
            model=_VERTEX_MODEL,
            vertexai=True,
            project=project,
            location=location,
            temperature=0.0,
            max_retries=6,
            thinking_level="low",
        )

    return ChatGoogleGenerativeAI(
        model=_VERTEX_MODEL,
        temperature=0.0,
        max_retries=6,
        thinking_level="low",
    )


llm = _build_llm()


def build_graph(checkpointer=None):
    """Build the LangGraph ReAct graph for booking_agent."""
    return create_react_agent(
        llm,
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


graph = build_graph()
