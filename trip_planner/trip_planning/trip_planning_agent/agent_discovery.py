"""Dynamic agent discovery via Google Cloud Agent Registry, replacing
hardcoded `RemoteA2aAgent` tool declarations, so the root agent can look up
"who can do X" at conversation time instead of the code naming specific
agents up front. New specialist agents become usable the moment they're
deployed AND registered, with no code change here.

Note: only CUSTOM-type entries (a resource's built-in query/streamQuery
interface) are auto-derived live from the Agent Engine resource itself.
A2A_AGENT-type entries — what this file actually searches for — are static
records that only exist/update if something explicitly runs `gcloud alpha
agent-registry services create|update`; each agent's own deploy_byoc.py does
this automatically after every deploy (see `_register_a2a_agent` there), so
sights_researcher and paypal_payments stay discoverable across redeploys
without a separate manual step.
"""

import os

from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.tools import FunctionTool, ToolContext
from google.adk.tools.agent_tool import AgentTool

from trip_planning_agent.auth import build_authed_httpx_client

# Non-agent Agent Engine resources in this project (shared session/memory
# storage) that show up in the registry alongside real A2A agents but have
# nothing to converse with.
_NOT_CALLABLE_AGENTS = {"trip-planner-shared-state", "trip-planner-memory-bank"}

_registry = AgentRegistry(
    project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
)
# Reasoning Engine BYOC endpoints require a Google Cloud bearer token on
# every request, same as the card fetch — see auth.py. Shared across
# discovered agents so repeated calls reuse one connection pool.
_httpx_client = build_authed_httpx_client()

# Resolving an agent_name into a RemoteA2aAgent hits Agent Registry and
# refreshes credentials on every call. The root agent's own instructions
# push it to reuse the same agent_name across many turns in one booking
# flow (research back-and-forth, then payment create/approve/capture), so
# without this cache every one of those turns would pay a full registry
# round trip. AgentTool itself is safe to reuse across calls — the actual
# conversation state lives in the caller's own session state (seeded fresh
# per call), not on the AgentTool instance.
_agent_tool_cache: dict[str, AgentTool] = {}


def _fresh_agent_tool(agent_name: str) -> AgentTool:
    remote_agent = _registry.get_remote_a2a_agent(agent_name=agent_name, httpx_client=_httpx_client)
    return AgentTool(agent=remote_agent)


def _to_match(agent: dict) -> dict:
    return {
        "agent_name": agent["name"],
        "display_name": agent.get("displayName", ""),
        "description": agent.get("description", ""),
        "skills": [
            {"name": s.get("name"), "description": s.get("description")}
            for s in agent.get("skills", [])
        ],
    }


def _is_callable_a2a_agent(agent: dict, own_name: str | None) -> bool:
    display_name = agent.get("displayName", "")
    if display_name in _NOT_CALLABLE_AGENTS or display_name == own_name:
        return False
    return any(p.get("type") == "A2A_AGENT" for p in agent.get("protocols", []))


async def discover_agents(capability: str, tool_context: ToolContext) -> dict:
    """Find other agents in Agent Registry that can help with a task.

    Call this whenever you need a specialist you haven't already discovered
    this conversation — e.g. "research travel destinations and build an
    itinerary" or "create and capture PayPal payments". Returns each match's
    `agent_name` (pass this to call_agent), display name, description, and
    skills, so you can judge fit before calling it. If nothing comes back,
    try a different word for the same capability before concluding no agent
    exists — registry search is keyword-based, not fuzzy.

    Args:
        capability: A short description of the capability or task you need
            help with, in plain language.
    """
    own_name = tool_context._invocation_context.agent.name if tool_context._invocation_context else None

    result = _registry.search_agents(search_string=capability, search_type="KEYWORD")
    matches = [
        _to_match(agent) for agent in result.get("agents", []) if _is_callable_a2a_agent(agent, own_name)
    ]

    if not matches:
        # Keyword search only matches literal substrings, so a phrase like
        # "build an itinerary" can miss an agent whose card just says
        # "places to see at a destination" — fall back to scanning every
        # registered agent's own words for a looser overlap.
        words = [w for w in capability.lower().split() if len(w) > 3]
        all_agents = _registry.list_agents().get("agents", [])
        for agent in all_agents:
            if not _is_callable_a2a_agent(agent, own_name):
                continue
            haystack = " ".join(
                [agent.get("displayName", ""), agent.get("description", "")]
                + [s.get("description", "") for s in agent.get("skills", [])]
            ).lower()
            if any(word in haystack for word in words):
                matches.append(_to_match(agent))

    if not matches:
        return {"found": False, "matches": []}
    return {"found": True, "matches": matches}


async def call_agent(agent_name: str, message: str, tool_context: ToolContext) -> str:
    """Send a message to another agent, found via discover_agents first.

    Treat this as a real, possibly slow network call to a whole separate
    conversational agent — not a local function. It may ask a follow-up
    question instead of finishing the task; relay that question onward
    rather than guessing an answer, then call this again with the answer
    once you have it.

    Args:
        agent_name: The `agent_name` field from a discover_agents match —
            Agent Registry's resource name for the target agent.
        message: What to ask or tell that agent, in plain language.
    """
    # The cached RemoteA2aAgent has last redeploy's resource URL baked in (see
    # _agent_tool_cache above) — if that agent has since been redeployed, its
    # resource id changed and this URL now 403s/404s even though Agent
    # Registry already points at the new one. RemoteA2aAgent swallows that
    # into a plain string return rather than raising, so a text match is the
    # only failure signal available here; refresh the lookup once and retry
    # before surfacing the failure.
    for attempt in range(2):
        agent_tool = _agent_tool_cache.get(agent_name)
        if agent_tool is None or attempt == 1:
            agent_tool = _agent_tool_cache[agent_name] = _fresh_agent_tool(agent_name)
        response = await agent_tool.run_async(args={"request": message}, tool_context=tool_context)
        if not response.startswith("A2A request failed"):
            break
    return response


discover_agents_tool = FunctionTool(discover_agents)
call_agent_tool = FunctionTool(call_agent)
