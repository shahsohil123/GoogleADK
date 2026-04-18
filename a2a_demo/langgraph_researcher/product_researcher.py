"""LangGraph product researcher, exposed as an A2A service.

Given a shopping request ("noise-cancelling headphones under $300 for long
flights"), this agent runs a small two-step LangGraph pipeline:

    find_candidates  ->  compare_and_rank

and returns a ranked shortlist over the A2A protocol. A downstream ADK
agent (see `adk_shopper.personal_shopper`) turns that into a friendly
recommendation for the shopper.

Run from the `a2a_demo/` directory:
    uvicorn langgraph_researcher.product_researcher:app --host 0.0.0.0 --port 8001
"""
import os
import warnings

os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
warnings.filterwarnings("ignore", category=UserWarning)

# Shim: langgraph >=1.0 moved/removed `langgraph.graph.graph.CompiledGraph`,
# but google.adk.agents.langgraph_agent still imports from that path.
import sys
import types

try:
    import langgraph.graph.graph as _lg_graph  # noqa: F401
except ModuleNotFoundError:
    _lg_graph = types.ModuleType("langgraph.graph.graph")
    sys.modules["langgraph.graph.graph"] = _lg_graph
if not hasattr(_lg_graph, "CompiledGraph"):
    from langgraph.graph.state import CompiledStateGraph
    _lg_graph.CompiledGraph = CompiledStateGraph

from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from google.adk.agents.langgraph_agent import LangGraphAgent
from google.adk.a2a.utils.agent_to_a2a import to_a2a


class State(TypedDict):
    messages: Annotated[list, add_messages]


def find_candidates_node(state: State):
    """Node 1: gather a shortlist of products matching the shopper's brief."""
    request = state["messages"][-1]
    query = request.content if hasattr(request, "content") else str(request)

    # In a real system this would call a product catalog, Google Shopping,
    # a price-comparison API, or a vector store of reviews. For the demo we
    # return a hand-curated shortlist based on the free-text query.
    shortlist = (
        f"[Candidate Shortlist] For the brief {query!r}:\n"
        "  1. Sony WH-1000XM5 — $329 list (often $279 on sale). "
        "Class-leading ANC, 30h battery, great call quality.\n"
        "  2. Bose QuietComfort Ultra — $379 list. "
        "Most comfortable on long flights, slightly weaker app.\n"
        "  3. Sennheiser Momentum 4 — $299. "
        "Best sound quality of the three, 60h battery, heavier.\n"
        "  4. Apple AirPods Max — $449. "
        "Best if you live in the Apple ecosystem, pricey and heavy.\n"
        "  5. Sony WH-1000XM4 (previous gen) — $229. "
        "Great value, slightly bulkier, ANC a step behind XM5."
    )
    return {"messages": [AIMessage(content=shortlist)]}


def compare_and_rank_node(state: State):
    """Node 2: weigh the candidates against the brief and rank them."""
    ranking = (
        "[Ranked Comparison] Weighted against the brief (under $300, "
        "long-flight comfort, strong ANC):\n"
        "  Top pick: Sony WH-1000XM5 at $279 on sale — best overall balance "
        "of ANC, comfort, and battery within budget.\n"
        "  Runner-up: Sennheiser Momentum 4 at $299 — pick this if sound "
        "quality matters more to you than peak ANC.\n"
        "  Budget play: Sony WH-1000XM4 at $229 — ~90% of the XM5 experience "
        "for ~$50 less. Best value in the list.\n"
        "  Skip for this brief: Bose Ultra and AirPods Max — both over budget."
    )
    return {"messages": [AIMessage(content=ranking)]}


graph_builder = StateGraph(State)
graph_builder.add_node("find_candidates", find_candidates_node)
graph_builder.add_node("compare_and_rank", compare_and_rank_node)
graph_builder.add_edge(START, "find_candidates")
graph_builder.add_edge("find_candidates", "compare_and_rank")
graph_builder.add_edge("compare_and_rank", END)

# ADK's LangGraphAgent resumes graphs per session, so a checkpointer is
# required. An in-memory saver is fine for the demo.
graph = graph_builder.compile(checkpointer=MemorySaver())


root_agent = LangGraphAgent(
    name="product_researcher",
    description=(
        "Product researcher. Accepts a free-text shopping brief "
        "(category, budget, use case, constraints) and returns a ranked "
        "shortlist with short justifications for each pick."
    ),
    graph=graph,
)

# Starlette app served via `uvicorn langgraph_researcher.product_researcher:app
# --port 8001`. Agent card auto-published at /.well-known/agent-card.json.
# RESEARCHER_HOST/RESEARCHER_PORT must match the uvicorn bind so the
# published card's RPC url matches where clients actually reach the server.
_HOST = os.environ.get("RESEARCHER_HOST", "localhost")
_PORT = int(os.environ.get("RESEARCHER_PORT", "8001"))
app = to_a2a(root_agent, host=_HOST, port=_PORT)