"""
AI Travel Concierge — Multi-Agent System

Architecture:
- travel_concierge (root coordinator) — orchestrates everything
  - researcher (AgentTool) — fetches web research
  - preferences_reader (AgentTool) — reads user profile files
  - itinerary_builder (sub_agent) — builds plans + handles approval loop

Using AgentTool for researcher/preferences so they return results cleanly.
Using sub_agent for itinerary_builder so it can handle multi-turn conversation.
"""

import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
warnings.filterwarnings("ignore", category=UserWarning)

from google.adk.agents import Agent
from google.adk.tools import AgentTool
from google.adk.tools.load_web_page import load_web_page

from agent.tools import (
    approve_day_tool,
    confirm_booking_tool,
    pause_tool,
    profile_tool,
    save_itinerary_tool,
    trips_tool,
)

RESOURCES_DIR = str(Path(__file__).parent.parent / "resources")
Path(RESOURCES_DIR).mkdir(parents=True, exist_ok=True)

MODEL = "gemini-3-flash-preview"


# ───────────────────────────────────────────────────────────────────────────
# Specialist agents
# ───────────────────────────────────────────────────────────────────────────

def create_researcher():
    return Agent(
        name="researcher",
        model=MODEL,
        description="Fetches real travel information from the web for a destination.",
        instruction="""\
You are a travel research specialist. Research the destination using load_web_page.

Use ONLY these reliable, scrapeable URLs — try them in order, skip any that fail:
- Wikipedia: https://en.wikipedia.org/wiki/<Destination_name>
- Wikitravel: https://wikitravel.org/en/<Destination_name>
- Wikivoyage: https://en.wikivoyage.org/wiki/<Destination_name>

Replace spaces with underscores in the URL (e.g. "New York City" → "New_York_City").

Try at least 2 URLs. If a URL fails, move on to the next — do NOT retry the same URL.

From the pages you successfully fetch, extract and return:
- Top 5 attractions with brief descriptions
- Best neighbourhoods to stay
- Local food highlights and vegetarian-friendly options
- Getting around (airport transfer + local transport)
- Rough cost estimates (hotel/night, meal, activity)
- 3–5 practical travel tips

If all URLs fail, use your own knowledge to provide the research — clearly note it.
""",
        tools=[load_web_page],
    )


def create_preferences_reader():
    return Agent(
        name="preferences_reader",
        model=MODEL,
        description="Reads the traveler's profile and past trips from local files.",
        instruction="""\
You are a traveler preferences specialist. Read the user's profile and trip history.

1. Call read_user_profile to get dietary needs, travel style, and interests
2. Call read_past_trips to get trip history and what they loved or disliked

Return a concise summary: dietary restrictions, activity interests, budget style,
what to include, and what to avoid based on past trips.
""",
        tools=[profile_tool, trips_tool],
    )


def create_itinerary_builder():
    return Agent(
        name="itinerary_builder",
        model=MODEL,
        description=(
            "Builds a detailed day-by-day itinerary. "
            "Shows each day in full and waits for human approval before continuing."
        ),
        instruction="""\
You are an expert itinerary builder. Build the trip plan one day at a time.

SESSION STATE: The coordinator has already stored research and preferences.
- Research findings: check state key 'research_findings'
- User preferences: check state key 'user_preferences'

WORKFLOW per day:
1. Write out the FULL day plan in detail:
   - 09:00  Activity name — why it fits the traveler + cost
   - 12:30  Lunch at [specific place] — why it's suitable + cost
   - 14:00  Afternoon activity + cost
   - 19:00  Dinner at [specific place] + cost
   - 21:00  Evening activity or rest
   - Transport notes between locations
   - Daily total estimate

2. End with: "Does Day [N] look good? Reply **approve** to move on,
   or tell me what to change."

3. When user says approve (or similar): call record_day_approval tool, then plan next day.

4. If user gives feedback: revise the plan and show it again.

After ALL days approved:
1. Print the full multi-day summary
2. Ask: "Your full trip is ready! Reply **book it** to confirm."
3. When user confirms: call record_final_booking, then save_itinerary_to_file.

RULES:
- Show the plan BEFORE asking for approval — never ask blind
- Honour all dietary restrictions in every meal
- Personalise based on research and preferences
- Never use confirmation dialogs — only plain text + wait
""",
        tools=[
            approve_day_tool,
            confirm_booking_tool,
            pause_tool,
            save_itinerary_tool,
        ],
    )


# ───────────────────────────────────────────────────────────────────────────
# Root coordinator
# ───────────────────────────────────────────────────────────────────────────

root_agent = Agent(
    name="travel_concierge",
    model=MODEL,
    description="AI Travel Concierge — plans personalised trips with a team of specialist agents.",
    instruction="""\
You are the AI Travel Concierge. Coordinate three specialist agents to plan the perfect trip.

STEP 1 — Read preferences
Call the preferences_reader agent tool with the user's trip request.
It will return a preference summary. Store it in state as 'user_preferences'.

STEP 2 — Research destination
Call the researcher agent tool with the destination name.
It will return detailed research. Store it in state as 'research_findings'.

STEP 3 — Hand off to itinerary builder
Transfer to itinerary_builder. It will build the plan day-by-day,
asking the user to approve each day before continuing.

IMPORTANT:
- Complete Step 1 and Step 2 before transferring to itinerary_builder
- Do not loop back once itinerary_builder has started
- Once itinerary_builder is running, let it handle all conversation with the user
""",
    tools=[
        AgentTool(create_researcher()),
        AgentTool(create_preferences_reader()),
    ],
    sub_agents=[
        create_itinerary_builder(),
    ],
)
