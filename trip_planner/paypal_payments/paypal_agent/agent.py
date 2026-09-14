"""LangGraph PayPal payments agent, exposed as an A2A service.

Run from the `paypal_payments/` directory:
    uvicorn paypal_agent.agent:app --host 0.0.0.0 --port 8002
"""
import os

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill

from paypal_agent.agent_executor import PayPalAgentExecutor

# Must match the uvicorn bind (see Makefile) so the published agent card's
# `url` matches where clients actually reach the server, locally.
_HOST = "localhost"
_PORT = 8002


def _rpc_url() -> str:
    """Local bind address, or the Agent Engine passthrough URL once deployed."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION")
    engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
    if project and location and engine_id:
        resource = f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"
        return f"https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api/"
    return f"http://{_HOST}:{_PORT}/"

skills = [
    AgentSkill(
        id="paypal_payments",
        name="PayPal Payments",
        description=(
            "Creates PayPal Sandbox orders, captures payment once the buyer "
            "approves, and issues full or partial refunds. Flow: create_order "
            "returns an order id and buyer approval link; once approved, "
            "pay_order captures it; create_refund then needs the capture id "
            "(from get_order, not the order id) to refund it. get_order and "
            "get_refund look up status by id at any point, and "
            "list_transactions summarizes everything booked, paid, or "
            "refunded so far."
        ),
        tags=["payments", "order", "refund", "checkout", "transactions"],
        examples=[
            "Create a $25 order for a yearly subscription.",
            "Capture order 5O190127TN364715T.",
            "Refund $10 of capture 3C679366HH908993F.",
        ],
    ),
]

agent_card = AgentCard(
    name="paypal_payments_agent",
    description="PayPal Sandbox payments agent built with LangGraph.",
    url=_rpc_url(),
    documentation_url="https://github.com/shahsohil123/GoogleADK/tree/main/trip_planner/paypal_payments",
    provider=AgentProvider(organization="trip_planner demo", url=f"http://{_HOST}:{_PORT}/"),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=False),
    skills=skills,
)

# Agent card auto-published at /.well-known/agent-card.json.
app = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=DefaultRequestHandler(
        agent_executor=PayPalAgentExecutor(),
        task_store=InMemoryTaskStore(),
    ),
).build()
