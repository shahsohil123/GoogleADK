#!/usr/bin/env python3
"""
Run the Travel Concierge agent programmatically.

This demonstrates the long-running pause/resume workflow:
- Agent plans day-by-day
- Pauses after each day for human approval
- Resumes with feedback incorporated

Usage:
    python run.py                          # Interactive mode
    python run.py --query "Plan a 3-day trip to Tokyo"
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Ensure agent module is importable
sys.path.insert(0, os.path.dirname(__file__))

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.agent import root_agent


async def run_interactive():
    """Run the agent in interactive mode with pause/resume support."""
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="travel_concierge",
        user_id="traveler",
    )

    runner = Runner(
        agent=root_agent,
        app_name="travel_concierge",
        session_service=session_service,
    )

    print("=" * 60)
    print("  AI Travel Concierge")
    print("  Type your travel request to get started.")
    print("  Type 'quit' to exit.")
    print("=" * 60)
    print()

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bon voyage!")
            break

        print()
        async for event in runner.run_async(
            user_id="traveler",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=user_input)],
            ),
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(part.text, end="", flush=True)

            # Check for tool confirmation requests (human-in-the-loop)
            if (
                event.actions
                and hasattr(event.actions, "requested_auth_configs")
                and event.actions.requested_auth_configs
            ):
                print("\n[Human approval requested — check the ADK web UI]")

        print("\n")


async def run_single_query(query: str):
    """Run a single query and print the response."""
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="travel_concierge",
        user_id="traveler",
    )

    runner = Runner(
        agent=root_agent,
        app_name="travel_concierge",
        session_service=session_service,
    )

    async for event in runner.run_async(
        user_id="traveler",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=query)],
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text)


def main():
    parser = argparse.ArgumentParser(description="AI Travel Concierge")
    parser.add_argument("--query", "-q", help="Single query mode")
    args = parser.parse_args()

    if args.query:
        asyncio.run(run_single_query(args.query))
    else:
        asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
