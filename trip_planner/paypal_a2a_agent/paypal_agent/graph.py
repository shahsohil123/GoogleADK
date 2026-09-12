"""The LangGraph ReAct graph itself, kept free of any A2A wrapping.

Split out from `agent.py`/`agent_executor.py` so LangGraph Studio
(`langgraph dev`) can load `graph` directly via `langgraph.json`, without
starting an A2A service.
"""
import os

from langgraph.prebuilt import create_react_agent

from paypal_agent.tools import ALL_TOOLS

SYSTEM_PROMPT = (
    "You are a PayPal payments assistant operating against the PayPal "
    "Sandbox, using PayPal's own tools: create_order, get_order, pay_order "
    "(captures an approved order), create_refund, get_refund, and "
    "list_transactions. Assume USD unless the user states a different "
    "currency. Always state amounts and currencies explicitly, surface "
    "the order/capture/refund id involved, and never claim a payment "
    "captured or refunded unless the tool result confirms it. If "
    "an order has not been approved by the buyer yet, tell the user to "
    "open its approval link instead of trying to pay it. create_refund "
    "needs a capture id, not an order id — if you only have the order id, "
    "call get_order first to find its capture id. Use list_transactions "
    "when asked for a summary of everything booked, paid, or refunded so "
    "far. Every item passed to create_order must have a specific, human-"
    "readable description of what it's for (e.g. \"Flight from JFK to "
    "LAX\", \"2-night stay at Hotel Meridian\") — never leave it blank or "
    "generic, since that description is how a later list_transactions "
    "call identifies what each transaction was for."
)


def _build_llm():
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
        from langchain_google_vertexai import ChatVertexAI

        return ChatVertexAI(
            model="gemini-2.5-flash",
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model="gemini-3.7-flash")


llm = _build_llm()


def build_graph(checkpointer=None):
    """Build the ReAct graph. Pass a checkpointer for `PayPalAgentExecutor`,
    which resumes the graph per A2A session itself. Leave it None for the
    LangGraph API server (Studio), which manages persistence on its own
    and rejects graphs compiled with a custom checkpointer."""
    return create_react_agent(
        llm,
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


# Loaded by `langgraph.json` for LangGraph Studio — no checkpointer, since
# the API server provides its own persistence.
graph = build_graph()
