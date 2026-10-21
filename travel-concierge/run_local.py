#!/usr/bin/env python3
"""Run the Travel Concierge multi-agent system locally or against Cloud Agent Runtime.

- **Local Mode (`LOCAL_MODE=true`, default)**:
  Uses `InMemorySessionService` and `SharedInMemoryMemoryService` across ADK,
  LangGraph (`booking_agent`), and CrewAI (`pre_trip_agent`).
- **Cloud Mode (`LOCAL_MODE=false`, via `make run-cloud`)**:
  Uses `VertexAiSessionService`, `SharedVertexAiMemoryBankService`, Google Cloud
  Agent Registry, Cloud Trace, and `BigQueryAgentAnalyticsPlugin`.

Usage:
    uv run python run_local.py                                      # Interactive CLI
    uv run python run_local.py --query "Inspire me about Peru"      # Single query mode
    uv run python run_local.py --start-all-a2a                      # Start all 16 local A2A servers (:8001–:8016)
    uv run python run_local.py --start-all-a2a --with-chat          # Start all 16 A2A servers + interactive CLI
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")
os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
os.environ["ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"

logging.basicConfig(level=logging.CRITICAL)
for _name in ("google_adk", "google_genai", "httpx", "httpcore", "a2a", "opentelemetry", "vertexai"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")
os.environ.setdefault("LOCAL_MODE", "true")
if os.environ.get("LOCAL_MODE", "").lower() in ("0", "false", "no") and (ROOT_DIR / ".env.dev").exists():
    load_dotenv(ROOT_DIR / ".env.dev", override=True)

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

sys.path.insert(0, str(ROOT_DIR / "root_agent"))

AGENTS_PORTS: list[tuple[str, str, int, str]] = [
    ("root_agent", "root_concierge_agent.a2a_app:app", 8001, "Google ADK"),
    ("inspiration_agent", "inspiration_concierge_agent.a2a_app:app", 8002, "Google ADK"),
    ("planning_agent", "planning_concierge_agent.a2a_app:app", 8003, "Google ADK"),
    ("booking_agent", "booking_langgraph_agent.agent:app", 8004, "LangGraph"),
    ("pre_trip_agent", "pre_trip_crewai_agent.agent:app", 8005, "CrewAI"),
    ("in_trip_agent", "in_trip_concierge_agent.a2a_app:app", 8006, "Google ADK"),
    ("post_trip_agent", "post_trip_concierge_agent.a2a_app:app", 8007, "Google ADK"),
    ("place_agent", "place_concierge_agent.a2a_app:app", 8008, "Google ADK"),
    ("poi_agent", "poi_concierge_agent.a2a_app:app", 8009, "Google ADK"),
    ("flight_search_agent", "flight_search_concierge_agent.a2a_app:app", 8010, "Google ADK"),
    ("flight_seat_selection_agent", "flight_seat_concierge_agent.a2a_app:app", 8011, "Google ADK"),
    ("hotel_search_agent", "hotel_search_concierge_agent.a2a_app:app", 8012, "Google ADK"),
    ("hotel_room_selection_agent", "hotel_room_concierge_agent.a2a_app:app", 8013, "Google ADK"),
    ("itinerary_agent", "itinerary_concierge_agent.a2a_app:app", 8014, "Google ADK"),
    ("day_of_agent", "day_of_concierge_agent.a2a_app:app", 8015, "Google ADK"),
    ("trip_monitor_agent", "trip_monitor_concierge_agent.a2a_app:app", 8016, "Google ADK"),
]


DEFAULT_TRAVELER = os.environ.get("TRAVELER_NAME", "sohil")


async def run_interactive(user_id: str = DEFAULT_TRAVELER) -> None:
    """Run `root_concierge_agent` interactively."""
    from google.genai import types
    from root_concierge_agent.runner import create_runner

    runner = await create_runner()
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id=user_id)
    plugins = getattr(getattr(runner, "plugin_manager", None), "plugins", None)

    print("=" * 72)
    print(f"  Travel Concierge ({'Local Mode' if os.environ.get('LOCAL_MODE') == 'true' else 'Cloud Agent Runtime'})")
    print(f"  Traveler        : {user_id}")
    print(f"  Session Service : {type(runner.session_service).__name__}")
    print(f"  Memory Service  : {type(runner.memory_service).__name__}")
    print(f"  BigQuery Plugin : {'Enabled' if plugins else 'Disabled'}")
    print("  Type your travel request or 'quit' to exit.")
    print("=" * 72 + "\n")

    while True:
        try:
            user_input = input(f"{user_id}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBon voyage!")
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bon voyage!")
            break

        print("\nConcierge: ", end="", flush=True)
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=user_input)]),
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(part.text, end="", flush=True)
        print("\n")


async def run_single_query(query: str, user_id: str = DEFAULT_TRAVELER) -> str:
    """Run a single query against `root_concierge_agent`."""
    from google.genai import types
    from root_concierge_agent.runner import create_runner

    runner = await create_runner()
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id=user_id)

    final_chunks: list[str] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text)
                    final_chunks.append(part.text)
    return "\n".join(final_chunks)


def start_all_local_a2a_servers(with_chat: bool = False, user_id: str = DEFAULT_TRAVELER) -> None:
    """Spins up all 16 A2A microservices locally on ports 8001..8016 with LOCAL_MODE=true."""
    procs: list[subprocess.Popen] = []
    env = {**os.environ, "LOCAL_MODE": "true"}

    print("Starting all 16 Travel Concierge A2A microservices in LOCAL_MODE...")
    for folder, app_target, port, framework in AGENTS_PORTS:
        cmd = [
            sys.executable, "-m", "uvicorn", app_target,
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ]
        procs.append(subprocess.Popen(cmd, cwd=str(ROOT_DIR / folder), env={**env, "PORT": str(port)}))
        print(f"  [+] {folder:<28} ({framework:<10}) -> http://localhost:{port}/.well-known/agent-card.json")

    def _shutdown(*_args):
        print("\nStopping all 16 local A2A servers...")
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()

    signal.signal(signal.SIGINT, lambda *_: (_shutdown(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (_shutdown(), sys.exit(0)))

    try:
        time.sleep(2.5)
        if with_chat:
            asyncio.run(run_interactive(user_id=user_id))
        else:
            print("\nAll 16 local A2A servers are running. Press Ctrl+C to stop.")
            while True:
                time.sleep(1.0)
    finally:
        _shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Travel Concierge locally or against Cloud Agent Runtime")
    parser.add_argument("--query", "-q", help="Run a single query against root_concierge_agent")
    parser.add_argument("--start-all-a2a", action="store_true", help="Start all 16 local A2A servers (:8001..:8016)")
    parser.add_argument("--with-chat", action="store_true", help="Also launch interactive CLI chat")
    parser.add_argument(
        "--traveler",
        "--user-id",
        dest="user_id",
        default=DEFAULT_TRAVELER,
        help="Traveler name / user_id for Session & Memory Bank (default: sohil)",
    )
    args = parser.parse_args()

    if args.start_all_a2a:
        start_all_local_a2a_servers(with_chat=args.with_chat, user_id=args.user_id)
    elif args.query:
        asyncio.run(run_single_query(args.query, user_id=args.user_id))
    else:
        asyncio.run(run_interactive(user_id=args.user_id))


if __name__ == "__main__":
    main()
