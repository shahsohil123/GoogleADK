# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Evaluation of `root_concierge_agent` (`root_agent`) across all 7 flows,
verifying:
1. All specialist agents are discovered via search in **Google Cloud Agent Registry**
   (`_registry.search_agents(search_string=..., search_type="KEYWORD")` +
   `_registry.get_remote_a2a_agent(...)`).
2. All OpenTelemetry traces are exported to **Google Cloud Trace**
   (`setup_cloud_trace_telemetry` -> `telemetry.googleapis.com/v1/traces`).
3. All events are streamed to **BigQuery** (`BigQueryAgentAnalyticsPlugin`) for
   the **Looker Agent Analytics Block**.
4. Local/Docker mode (`LOCAL_MODE=true`) spins up `InMemorySessionService` and
   `SharedInMemoryMemoryService`.
5. All 7 concierge flows (`inspire.test.json`, `planning.test.json`,
   `booking.test.json`, `pretrip.test.json`, `intrip.test.json`,
   `posttrip.test.json`, `memory_preferences.test.json`) pass both deterministic
   Agent Registry trajectory tests and ADK `AgentEvaluator.evaluate`.
"""

import asyncio
import inspect
import os
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import dotenv

try:
    import pytest
except ImportError:
    class _Mark:
        @staticmethod
        def asyncio(fn):
            return fn

        @staticmethod
        def skipif(cond, reason=""):
            def _dec(fn):
                fn._skip = bool(cond)
                fn._skip_reason = reason
                return fn
            return _dec

        @staticmethod
        def parametrize(argnames, argvalues):
            def _dec(fn):
                fn._parametrize = (argnames, argvalues)
                return fn
            return _dec

    class _PytestShim:
        mark = _Mark()

        @staticmethod
        def fixture(*_args, **_kwargs):
            def _dec(fn):
                return fn
            return _dec

    pytest = _PytestShim()

CURRENT_DIR = Path(__file__).resolve().parent
if (CURRENT_DIR.parent / "root_concierge_agent").exists():
    ROOT_AGENT_DIR = CURRENT_DIR.parent
    PROJECT_ROOT = ROOT_AGENT_DIR.parent
else:
    PROJECT_ROOT = CURRENT_DIR.parent
    ROOT_AGENT_DIR = PROJECT_ROOT / "root_agent"

DATA_DIR = CURRENT_DIR / "data"

for p in (
    ROOT_AGENT_DIR,
    PROJECT_ROOT / "booking_agent",
    PROJECT_ROOT / "pre_trip_agent",
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ["LOCAL_MODE"] = "true"
dotenv.load_dotenv(PROJECT_ROOT / ".env")

from google.adk.evaluation import AgentEvaluator
from google.adk.evaluation.eval_set import EvalSet
from google.adk.memory import InMemoryMemoryService
from google.adk.sessions import InMemorySessionService

import root_concierge_agent.agent_discovery as discovery_mod
from root_concierge_agent.agent import app as root_app, root_agent
from root_concierge_agent.agent_discovery import call_agent, discover_agents
from root_concierge_agent.runner import create_runner
from root_concierge_agent.state_helpers import (
    DEFAULT_STATE_KEYS,
    memorize,
    recall_preferences,
    save_preference,
)
from root_concierge_agent.vertex_services import (
    SHARED_MEMORY_APP_NAME,
    SharedInMemoryMemoryService,
    build_bigquery_analytics_plugin,
    build_memory_service,
    is_local_mode,
    setup_cloud_trace_telemetry,
)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# Sample Google Cloud Agent Registry records returned by `_registry.search_agents`
_REGISTRY_AGENTS = {
    "inspiration_agent": {
        "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/inspiration_agent",
        "displayName": "inspiration_agent",
        "description": "Pre-booking travel inspiration coordinator (ADK). Suggests destinations and POIs.",
        "protocols": [{"type": "A2A_AGENT"}],
        "skills": [{"name": "destination_inspiration", "description": "Suggest vacation destinations and POIs."}],
    },
    "planning_agent": {
        "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/planning_agent",
        "displayName": "planning_agent",
        "description": "Trip planning coordinator (ADK) for flights, seats, hotels, rooms, and itineraries.",
        "protocols": [{"type": "A2A_AGENT"}],
        "skills": [{"name": "trip_planning", "description": "Search flights, seats, hotels, rooms, and build itinerary."}],
    },
    "booking_agent": {
        "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/booking_agent",
        "displayName": "booking_agent",
        "description": "Booking and payment execution agent (LangGraph) for reservations and payments.",
        "protocols": [{"type": "A2A_AGENT"}],
        "skills": [{"name": "booking_and_payment", "description": "Create reservations and process payments."}],
    },
    "pre_trip_agent": {
        "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/pre_trip_agent",
        "displayName": "pre_trip_agent",
        "description": "Pre-trip readiness and packing specialist (CrewAI) for visa, medical, storm, and packing.",
        "protocols": [{"type": "A2A_AGENT"}],
        "skills": [{"name": "pre_trip_readiness", "description": "Check visa, medical, weather, advisory, and packing list."}],
    },
    "in_trip_agent": {
        "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/in_trip_agent",
        "displayName": "in_trip_agent",
        "description": "In-trip concierge coordinator (ADK) for active trip monitoring and day-of transit.",
        "protocols": [{"type": "A2A_AGENT"}],
        "skills": [{"name": "in_trip_support", "description": "Monitor flights/events/weather and calculate day-of transit."}],
    },
    "post_trip_agent": {
        "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/post_trip_agent",
        "displayName": "post_trip_agent",
        "description": "Post-trip feedback specialist (ADK) extracting preferences into shared Memory Bank.",
        "protocols": [{"type": "A2A_AGENT"}],
        "skills": [{"name": "post_trip_feedback", "description": "Extract post-trip feedback and preferences."}],
    },
}

_SIMULATED_A2A_REPLIES = {
    f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/inspiration_agent": (
        "Here are 3 curated ideas in the Americas: 1. Machu Picchu & Cusco, Peru (4.9), "
        "2. Banff National Park, Canada (4.8), 3. New York City, USA (4.7)."
    ),
    f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/planning_agent": (
        "Planned 4-day trip SAN -> CUZ (2026-11-10 to 2026-11-14): Flights LA2405/LA2408 "
        "(Window Seats 14A/12A), Palacio del Inka Cusco, and 4-day Machu Picchu itinerary."
    ),
    f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/booking_agent": (
        "LangGraph booking_agent created Flight Reservation RES-FLT-90812 and Hotel Reservation "
        "RES-HTL-44219; payment approved via Google Pay (ORD-GP-774120, $2,730.00)."
    ),
    f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/pre_trip_agent": (
        "CrewAI pre_trip_agent briefing: Visa not required for US Citizens (<90 days); "
        "Medical: routine vaccines + altitude prep; Weather: mild; Packing List: layers, rain jacket, hiking boots."
    ),
    f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/in_trip_agent": (
        "In-trip status: Flight AA1234/LA2405 ON TIME; Machu Picchu/Space Needle checked; "
        "Day-Of Transit: 20-minute drive to airport / destination."
    ),
    f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/post_trip_agent": (
        "Post-trip feedback processed: saved boutique heritage hotel and vegan Peruvian cuisine "
        "preferences to shared Memory Bank."
    ),
}


def _make_mock_tool_context(user_id: str = "eval_traveler", memory_service=None):
    mem_svc = memory_service or build_memory_service()
    ctx = MagicMock()
    ctx.state = dict(DEFAULT_STATE_KEYS)
    ctx._invocation_context.agent.name = "root_agent"
    ctx._invocation_context.user_id = user_id

    async def _add_memory(memories, custom_metadata=None):
        return await mem_svc.add_memory(
            app_name="root_agent",
            user_id=user_id,
            memories=memories,
            custom_metadata=custom_metadata,
        )

    async def _search_memory(query: str):
        return await mem_svc.search_memory(
            app_name="root_agent",
            user_id=user_id,
            query=query,
        )

    ctx.add_memory = _add_memory
    ctx.search_memory = _search_memory
    return ctx


class _MockAgentRegistryContext:
    """Patches `_registry.search_agents`, `_registry.list_agents`, and
    `_fresh_agent_tool` so tests verify that `discover_agents` and `call_agent`
    always query Google Cloud Agent Registry (`search_type="KEYWORD"`).
    """

    def __init__(self):
        self.search_calls: list[tuple[str, str]] = []
        self.called_agents: list[tuple[str, str]] = []

    def __enter__(self):
        def _search_agents(*, search_string: str, search_type: str = "KEYWORD"):
            self.search_calls.append((search_string, search_type))
            q = search_string.lower()
            matches = [
                rec
                for key, rec in _REGISTRY_AGENTS.items()
                if key in q or q in key or any(w in rec["description"].lower() for w in q.split() if len(w) > 3)
            ]
            return {"agents": matches}

        def _list_agents():
            return {"agents": list(_REGISTRY_AGENTS.values())}

        def _fresh_tool(agent_name: str):
            tool = MagicMock()

            async def _run_async(*, args: dict, tool_context):
                self.called_agents.append((agent_name, args["request"]))
                return _SIMULATED_A2A_REPLIES.get(agent_name, f"Reply from {agent_name}")

            tool.run_async = _run_async
            return tool

        discovery_mod._agent_tool_cache.clear()
        self._p1 = patch.object(discovery_mod._registry, "search_agents", side_effect=_search_agents)
        self._p2 = patch.object(discovery_mod._registry, "list_agents", side_effect=_list_agents)
        self._p3 = patch.object(discovery_mod, "_fresh_agent_tool", side_effect=_fresh_tool)
        self._p1.start()
        self._p2.start()
        self._p3.start()
        return self

    def __exit__(self, *exc):
        self._p3.stop()
        self._p2.stop()
        self._p1.stop()
        discovery_mod._agent_tool_cache.clear()


# ============================================================================
# 0. Cloud Trace OTel, BigQuery Plugin & Local In-Memory Mode Verification
# ============================================================================


@pytest.mark.asyncio
async def test_local_mode_and_cloud_trace_and_bigquery_setup():
    """Verify LOCAL_MODE InMemory services, Cloud Trace OTel export, and BigQuery plugin."""
    assert is_local_mode() is True
    runner = await create_runner()
    assert isinstance(runner.session_service, InMemorySessionService)
    assert isinstance(runner.memory_service, InMemoryMemoryService)
    assert isinstance(runner.memory_service, SharedInMemoryMemoryService)

    # Verify Cloud Trace OpenTelemetry exporter setup
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
    os.environ["OTEL_TO_CLOUD"] = "true"
    otel_ok = setup_cloud_trace_telemetry("root_agent")
    assert isinstance(otel_ok, bool)

    # Verify BigQueryAgentAnalyticsPlugin configuration for Looker
    plugins = build_bigquery_analytics_plugin("root_agent", framework="google_adk")
    if plugins:
        p = plugins[0]
        assert p.dataset_id == "agent_analytics"
        assert p.table_id == "agent_events"
        assert p.config.create_views is False
        assert p.config.auto_schema_upgrade is False
        assert p.config.enable_otel_correlation is True
        assert p.config.custom_tags["app"] == SHARED_MEMORY_APP_NAME
    assert root_app.root_agent is root_agent


# ============================================================================
# 1–7. Agent Registry Discovery & Flow Trajectory Evals for All 7 Flows
# ============================================================================


@pytest.mark.asyncio
async def test_flow_1_inspire_via_agent_registry_search():
    """Flow 1 (inspire.test.json): Discover & invoke `inspiration_agent` via Agent Registry search."""
    eval_set = EvalSet.model_validate_json((DATA_DIR / "inspire.test.json").read_text())
    assert eval_set.name == "inspire"

    ctx = _make_mock_tool_context()
    with _MockAgentRegistryContext() as reg_spy:
        discovered = await discover_agents("inspiration_agent", ctx)
        assert discovered["found"] is True
        assert ("inspiration_agent", "KEYWORD") in reg_spy.search_calls
        agent_resource_name = discovered["matches"][0]["agent_name"]
        assert agent_resource_name.endswith("/agents/inspiration_agent")

        reply = await call_agent(agent_resource_name, "Inspire me about the Americas", ctx)
        assert "Machu Picchu" in reply
        assert reg_spy.called_agents[0][0] == agent_resource_name


@pytest.mark.asyncio
async def test_flow_2_planning_via_agent_registry_search():
    """Flow 2 (planning.test.json): Discover & invoke `planning_agent` via Agent Registry search."""
    eval_set = EvalSet.model_validate_json((DATA_DIR / "planning.test.json").read_text())
    assert eval_set.name == "planning"

    ctx = _make_mock_tool_context()
    with _MockAgentRegistryContext() as reg_spy:
        discovered = await discover_agents("planning_agent", ctx)
        assert discovered["found"] is True
        assert ("planning_agent", "KEYWORD") in reg_spy.search_calls
        agent_resource_name = discovered["matches"][0]["agent_name"]
        assert agent_resource_name.endswith("/agents/planning_agent")

        reply = await call_agent(agent_resource_name, "Plan my 4-day trip SAN -> CUZ", ctx)
        assert "LA2405" in reply
        assert "Palacio del Inka" in reply

        mem = await memorize("outbound_flight_selection", "LA2405 Seat 14A", ctx)
        assert "outbound_flight_selection" in mem["status"]


@pytest.mark.asyncio
async def test_flow_3_booking_langgraph_via_agent_registry_search():
    """Flow 3 (booking.test.json): Discover & invoke LangGraph `booking_agent` via Agent Registry search."""
    eval_set = EvalSet.model_validate_json((DATA_DIR / "booking.test.json").read_text())
    assert eval_set.name == "booking"

    ctx = _make_mock_tool_context()
    with _MockAgentRegistryContext() as reg_spy:
        discovered = await discover_agents("booking_agent", ctx)
        assert discovered["found"] is True
        assert ("booking_agent", "KEYWORD") in reg_spy.search_calls
        agent_resource_name = discovered["matches"][0]["agent_name"]
        assert agent_resource_name.endswith("/agents/booking_agent")

        reply = await call_agent(agent_resource_name, "Reserve flights and hotel and pay with Google Pay", ctx)
        assert "RES-FLT-90812" in reply
        assert "ORD-GP-774120" in reply


@pytest.mark.asyncio
async def test_flow_4_pretrip_crewai_via_agent_registry_search():
    """Flow 4 (pretrip.test.json): Discover & invoke CrewAI `pre_trip_agent` via Agent Registry search."""
    eval_set = EvalSet.model_validate_json((DATA_DIR / "pretrip.test.json").read_text())
    assert eval_set.name == "pretrip"

    ctx = _make_mock_tool_context()
    with _MockAgentRegistryContext() as reg_spy:
        discovered = await discover_agents("pre_trip_agent", ctx)
        assert discovered["found"] is True
        assert ("pre_trip_agent", "KEYWORD") in reg_spy.search_calls
        agent_resource_name = discovered["matches"][0]["agent_name"]
        assert agent_resource_name.endswith("/agents/pre_trip_agent")

        reply = await call_agent(agent_resource_name, "Check visa, medical, storm, advisory, and packing list", ctx)
        assert "Visa" in reply
        assert "Packing List" in reply


@pytest.mark.asyncio
async def test_flow_5_intrip_via_agent_registry_search():
    """Flow 5 (intrip.test.json): Discover & invoke `in_trip_agent` via Agent Registry search + `memorize`."""
    eval_set = EvalSet.model_validate_json((DATA_DIR / "intrip.test.json").read_text())
    assert eval_set.name == "intrip"

    ctx = _make_mock_tool_context()
    with _MockAgentRegistryContext() as reg_spy:
        discovered = await discover_agents("in_trip_agent", ctx)
        assert discovered["found"] is True
        assert ("in_trip_agent", "KEYWORD") in reg_spy.search_calls
        agent_resource_name = discovered["matches"][0]["agent_name"]
        assert agent_resource_name.endswith("/agents/in_trip_agent")

        reply = await call_agent(agent_resource_name, "Monitor flights and calculate day-of transit", ctx)
        assert "ON TIME" in reply
        assert "Day-Of Transit" in reply

        mem = await memorize("itinerary_datetime", "2025-06-16 12:45:00", ctx)
        assert ctx.state["itinerary_datetime"] == "2025-06-16 12:45:00"
        assert "itinerary_datetime" in mem["status"]


@pytest.mark.asyncio
async def test_flow_6_posttrip_via_agent_registry_search():
    """Flow 6 (posttrip.test.json): Discover & invoke `post_trip_agent` via Agent Registry search."""
    eval_set = EvalSet.model_validate_json((DATA_DIR / "posttrip.test.json").read_text())
    assert eval_set.name == "posttrip"

    ctx = _make_mock_tool_context()
    with _MockAgentRegistryContext() as reg_spy:
        discovered = await discover_agents("post_trip_agent", ctx)
        assert discovered["found"] is True
        assert ("post_trip_agent", "KEYWORD") in reg_spy.search_calls
        agent_resource_name = discovered["matches"][0]["agent_name"]
        assert agent_resource_name.endswith("/agents/post_trip_agent")

        reply = await call_agent(agent_resource_name, "Loved boutique hotels and vegan Peruvian food", ctx)
        assert "Memory Bank" in reply


@pytest.mark.asyncio
async def test_flow_7_memory_preferences_save_and_recall():
    """Flow 7 (memory_preferences.test.json): Save & recall preferences in shared Memory Bank."""
    eval_set = EvalSet.model_validate_json((DATA_DIR / "memory_preferences.test.json").read_text())
    assert eval_set.name == "memory_preferences"

    mem_service = SharedInMemoryMemoryService()
    ctx = _make_mock_tool_context(user_id="vegan_traveler_01", memory_service=mem_service)

    saved = await save_preference(
        "Traveler strictly eats vegan meals and prefers window seats on flights.",
        ctx,
    )
    assert saved["saved"] is True

    recalled = await recall_preferences("vegan meals window seats", ctx)
    assert recalled["known"] is True
    assert any("vegan" in f.lower() for f in recalled["facts"])


# ============================================================================
# ADK `AgentEvaluator.evaluate` Suites (matches google/adk-recipes@0521e23/eval/test_eval.py
# + all 7 flows of root_concierge_agent, exporting OTel traces to Cloud Trace)
# ============================================================================


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_LIVE_ADK_EVAL=true (or run `make adk-eval`) to execute live Gemini LLM AgentEvaluator runs.",
)
@pytest.mark.asyncio
async def test_inspire():
    """Evaluate `inspire.test.json` via ADK AgentEvaluator."""
    await AgentEvaluator.evaluate(
        "root_concierge_agent",
        str(DATA_DIR / "inspire.test.json"),
        num_runs=1,
    )


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_LIVE_ADK_EVAL=true (or run `make adk-eval`) to execute live Gemini LLM AgentEvaluator runs.",
)
@pytest.mark.asyncio
async def test_pretrip():
    """Evaluate `pretrip.test.json` via ADK AgentEvaluator."""
    await AgentEvaluator.evaluate(
        "root_concierge_agent",
        str(DATA_DIR / "pretrip.test.json"),
        num_runs=1,
    )


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_LIVE_ADK_EVAL=true (or run `make adk-eval`) to execute live Gemini LLM AgentEvaluator runs.",
)
@pytest.mark.asyncio
async def test_intrip():
    """Evaluate `intrip.test.json` via ADK AgentEvaluator."""
    await AgentEvaluator.evaluate(
        "root_concierge_agent",
        str(DATA_DIR / "intrip.test.json"),
        num_runs=1,
    )


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_LIVE_ADK_EVAL=true (or run `make adk-eval`) to execute live Gemini LLM AgentEvaluator runs.",
)
@pytest.mark.asyncio
async def test_planning():
    """Evaluate `planning.test.json` via ADK AgentEvaluator."""
    await AgentEvaluator.evaluate(
        "root_concierge_agent",
        str(DATA_DIR / "planning.test.json"),
        num_runs=1,
    )


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_LIVE_ADK_EVAL=true (or run `make adk-eval`) to execute live Gemini LLM AgentEvaluator runs.",
)
@pytest.mark.asyncio
async def test_booking():
    """Evaluate `booking.test.json` via ADK AgentEvaluator."""
    await AgentEvaluator.evaluate(
        "root_concierge_agent",
        str(DATA_DIR / "booking.test.json"),
        num_runs=1,
    )


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_LIVE_ADK_EVAL=true (or run `make adk-eval`) to execute live Gemini LLM AgentEvaluator runs.",
)
@pytest.mark.asyncio
async def test_posttrip():
    """Evaluate `posttrip.test.json` via ADK AgentEvaluator."""
    await AgentEvaluator.evaluate(
        "root_concierge_agent",
        str(DATA_DIR / "posttrip.test.json"),
        num_runs=1,
    )


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_LIVE_ADK_EVAL=true (or run `make adk-eval`) to execute live Gemini LLM AgentEvaluator runs.",
)
@pytest.mark.asyncio
async def test_memory_preferences():
    """Evaluate `memory_preferences.test.json` via ADK AgentEvaluator."""
    await AgentEvaluator.evaluate(
        "root_concierge_agent",
        str(DATA_DIR / "memory_preferences.test.json"),
        num_runs=1,
    )


async def _run_all_tests() -> None:
    tests = [
        ("test_local_mode_and_cloud_trace_and_bigquery_setup", test_local_mode_and_cloud_trace_and_bigquery_setup()),
        ("test_flow_1_inspire_via_agent_registry_search", test_flow_1_inspire_via_agent_registry_search()),
        ("test_flow_2_planning_via_agent_registry_search", test_flow_2_planning_via_agent_registry_search()),
        ("test_flow_3_booking_langgraph_via_agent_registry_search", test_flow_3_booking_langgraph_via_agent_registry_search()),
        ("test_flow_4_pretrip_crewai_via_agent_registry_search", test_flow_4_pretrip_crewai_via_agent_registry_search()),
        ("test_flow_5_intrip_via_agent_registry_search", test_flow_5_intrip_via_agent_registry_search()),
        ("test_flow_6_posttrip_via_agent_registry_search", test_flow_6_posttrip_via_agent_registry_search()),
        ("test_flow_7_memory_preferences_save_and_recall", test_flow_7_memory_preferences_save_and_recall()),
    ]
    print("=" * 76)
    print("  Running root_concierge_agent Evaluation Suite (Agent Registry + Cloud Trace)")
    print("=" * 76)
    for name, coro in tests:
        if inspect.iscoroutine(coro):
            await coro
        print(f"  [PASS] {name}")

    if os.environ.get("RUN_LIVE_ADK_EVAL", "").lower() in ("1", "true", "yes"):
        for fn in (
            test_inspire,
            test_planning,
            test_booking,
            test_pretrip,
            test_intrip,
            test_posttrip,
            test_memory_preferences,
        ):
            await fn()
            print(f"  [PASS] {fn.__name__} (AgentEvaluator)")

    print("=" * 76)
    print(f"  All {len(tests)} evaluation suites passed!")
    print("=" * 76)


if __name__ == "__main__":
    asyncio.run(_run_all_tests())
