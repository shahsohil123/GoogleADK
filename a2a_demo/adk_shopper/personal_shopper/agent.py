"""ADK personal shopper that delegates product research to a remote
LangGraph agent over the A2A protocol.

This module exposes `root_agent` — the variable that `adk web` and
`adk run` look for when you point them at the parent directory.

Usage (run from the `a2a_demo/` directory):

    # terminal 1 — start the LangGraph product researcher:
    uvicorn langgraph_researcher.product_researcher:app --host 0.0.0.0 --port 8001

    # terminal 2 — launch the ADK dev UI; open the printed URL in a browser:
    adk web .
"""
import os
import warnings

os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
warnings.filterwarnings("ignore", category=UserWarning)

from google.adk import Agent
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)
from google.adk.tools.agent_tool import AgentTool

RESEARCHER_URL = os.environ.get("RESEARCHER_URL", "http://localhost:8001")

remote_researcher = RemoteA2aAgent(
    name="product_researcher",
    description=(
        "Remote product researcher (LangGraph). Accepts a shopping brief "
        "and returns a ranked shortlist of products with justifications."
    ),
    agent_card=f"{RESEARCHER_URL}{AGENT_CARD_WELL_KNOWN_PATH}",
)

root_agent = Agent(
    name="personal_shopper",
    model="gemini-2.5-flash",
    description=(
        "Warm, knowledgeable personal shopping concierge. Collects the "
        "customer's brief and delegates product research over A2A."
    ),
    instruction="""
You are a warm, knowledgeable personal shopping concierge. A customer will
describe something they want to buy.

Before recommending anything, you MUST call the `product_researcher` tool
with the customer's full brief (category, budget, use case, constraints)
so it can look up candidates and rank them. Once you have the ranked
shortlist back, synthesize a friendly, concise reply to the customer with:

  1. Your top pick — one sentence on why it wins for them
  2. A runner-up — one sentence on when they'd prefer it instead
  3. One sentence on what to skip and why

Keep the tone helpful and human — you're a trusted friend who happens to
know the category, not a spec sheet.
""",
    tools=[AgentTool(agent=remote_researcher)],
)