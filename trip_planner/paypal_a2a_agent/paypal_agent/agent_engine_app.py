"""Vertex AI Agent Engine wrapper around the LangGraph graph in `graph.py`.

Agent Engine's prebuilt `LanggraphAgent` template only exposes a synchronous
`query()` (it calls the compiled graph's `.invoke()`), but PayPal's MCP tools
are async-only — calling them synchronously raises `NotImplementedError`. So
this is a minimal custom Agent Engine app instead, exposing `async_query` per
Agent Engine's custom-template protocol (a plain class with `set_up()` and
`register_operations()`).
"""
from typing import Any, Mapping, Sequence

from langgraph.checkpoint.memory import MemorySaver


class PayPalAgentEngineApp:
    def set_up(self) -> None:
        from paypal_agent.graph import build_graph

        self._graph = build_graph(checkpointer=MemorySaver())

    async def async_query(self, *, input: str, config: Mapping[str, Any] | None = None) -> dict:
        result = await self._graph.ainvoke({"messages": [("user", input)]}, config=config)
        return {"output": result["messages"][-1].content}

    def register_operations(self) -> Mapping[str, Sequence[str]]:
        return {"async": ["async_query"]}
