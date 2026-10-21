"""CrewAI Crew for `pre_trip_agent`, wired to the shared Vertex AI Memory Bank."""

import os

from crewai import Agent, Crew, LLM, Process, Task

from pre_trip_crewai_agent.tools import (
    google_search_grounding,
    recall_shared_memory,
    save_shared_memory,
)


def _build_llm() -> LLM:
    model_name = os.environ.get("PRE_TRIP_MODEL", "vertex_ai/gemini-3-flash-preview")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEXAI_PROJECT")
    location = "global"
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["VERTEXAI_LOCATION"] = "global"
    if project:
        os.environ["VERTEXAI_PROJECT"] = project
    return LLM(model=model_name, temperature=0.2, num_retries=5, reasoning_effort="low")


def build_pre_trip_crew() -> Crew:
    llm = _build_llm()

    readiness_researcher = Agent(
        role="Pre-Trip Readiness & Travel Advisory Researcher",
        goal=(
            "Gather accurate, up-to-date pre-trip information for the traveler's "
            "upcoming itinerary covering visa requirements, medical/vaccination "
            "requirements, storm/weather monitoring, and official travel advisories."
        ),
        backstory=(
            "You are a seasoned pre-trip travel intelligence specialist. You use "
            "`recall_shared_memory` to check any stored itinerary or traveler profile "
            "facts in Vertex AI Memory Bank, and `google_search_grounding` to check "
            "visa requirements, medical requirements, storm/weather alerts, and travel "
            "advisories between the origin and destination."
        ),
        tools=[recall_shared_memory, google_search_grounding],
        llm=llm,
        verbose=False,
    )

    what_to_pack_specialist = Agent(
        role="What-To-Pack & Pre-Trip Briefing Specialist",
        goal=(
            "Recommend a tailored packing list for the trip's origin, destination, "
            "dates/season, and planned activities, persist it to the shared Vertex AI "
            "Memory Bank via `save_shared_memory`, and combine it with the travel "
            "readiness research into a clear, stress-free pre-trip summary."
        ),
        backstory=(
            "You are the `what_to_pack_agent` and pre-trip briefing coordinator. "
            "You synthesize visa, medical, storm, and travel advisory findings with "
            "a curated packing list appropriate for the destination and activities."
        ),
        tools=[save_shared_memory],
        llm=llm,
        verbose=False,
    )

    research_task = Task(
        description=(
            "Analyze the traveler's request and trip details below:\n"
            "{request}\n\n"
            "Recalled facts from shared Vertex AI Memory Bank:\n"
            "{memories}\n\n"
            "Conversation history from shared Vertex AI Session Service:\n"
            "{history}\n\n"
            "If any trip details (origin, destination, dates, passport nationality) "
            "are missing from the request, check `recall_shared_memory`. If still "
            "no destination or itinerary information is present at all, state clearly "
            "that an itinerary or destination is needed.\n"
            "Otherwise, identify the origin, destination, travel dates/season, and "
            "passport nationality (assume US Citizen if not provided), and call "
            "`google_search_grounding` to check:\n"
            "1. visa_requirements\n"
            "2. medical_requirements\n"
            "3. storm_monitor\n"
            "4. travel_advisory"
        ),
        expected_output=(
            "Structured findings covering visa requirements, medical requirements, "
            "storm/weather updates, and travel advisories for the trip."
        ),
        agent=readiness_researcher,
    )

    packing_and_briefing_task = Task(
        description=(
            "Using the readiness research from the previous task and the trip details in:\n"
            "{request}\n\n"
            "1. Generate a curated list of items to pack (`what_to_pack`) tailored to the "
            "destination, dates/season, and activities, and save the packing list summary "
            "using `save_shared_memory`.\n"
            "2. Produce a human-readable pre-trip briefing formatted with:\n"
            "   - visa: ...\n"
            "   - medical: ...\n"
            "   - travel advisory: ...\n"
            "   - storm update: ...\n"
            "   - what to pack: ..."
        ),
        expected_output=(
            "A friendly, comprehensive pre-trip readiness briefing containing visa, "
            "medical, travel advisory, storm update, and what-to-pack recommendations."
        ),
        agent=what_to_pack_specialist,
        context=[research_task],
    )

    return Crew(
        agents=[readiness_researcher, what_to_pack_specialist],
        tasks=[research_task, packing_and_briefing_task],
        process=Process.sequential,
        verbose=False,
    )
