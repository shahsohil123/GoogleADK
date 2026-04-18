"""ADK-side agent package — the customer-facing Personal Shopper.

`adk web` and `adk run` discover agents by importing the package and
looking for `agent.root_agent`. Don't remove this re-export.
"""
from . import agent

__all__ = ["agent"]