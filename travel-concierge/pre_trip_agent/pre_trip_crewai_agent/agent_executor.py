"""A2A `AgentExecutor` that drives the CrewAI `pre_trip_agent` Crew, backed by
`InMemory` (local mode) or the shared Vertex AI Session Service
(`SESSION_AGENT_ENGINE_ID`) and Memory Bank (`MEMORY_AGENT_ENGINE_ID`), and
streaming analytics to BigQuery for Looker.
"""

import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus

from pre_trip_crewai_agent.crew import build_pre_trip_crew
from pre_trip_crewai_agent.vertex_services import (
    append_vertex_session_turn,
    current_user_id,
    load_or_create_vertex_session,
    log_crewai_run_to_bigquery,
    search_memory_facts_sync,
)


def _extract_user_id(context: RequestContext) -> str:
    call_ctx = getattr(context, "call_context", None)
    user = getattr(call_ctx, "user", None) if call_ctx else None
    user_name = getattr(user, "user_name", None) if user else None
    return user_name or f"A2A_USER_{context.context_id}"


class PreTripAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        t0 = time.monotonic()
        query = context.get_user_input()
        user_id = _extract_user_id(context)
        current_user_id.set(user_id)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if not context.current_task:
            await event_queue.enqueue_event(
                Task(
                    id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                )
            )
        await updater.start_work()

        vertex_session_id, history_lines, _ = await load_or_create_vertex_session(
            context.context_id, user_id
        )
        history_str = "\n".join(history_lines[-6:]) if history_lines else "None"

        try:
            recalled = search_memory_facts_sync(
                "itinerary destination origin dates nationality preferences", user_id=user_id
            )
            memories_str = "\n".join(f"- {f}" for f in recalled) if recalled else "None"
        except Exception:
            memories_str = "None"

        crew = build_pre_trip_crew()
        result = await crew.kickoff_async(
            inputs={
                "request": query,
                "history": history_str,
                "memories": memories_str,
            }
        )
        reply_text = str(result.raw if hasattr(result, "raw") else result).strip() or (
            "The pre-trip CrewAI agent completed the check but returned no text."
        )

        await append_vertex_session_turn(
            session_id=vertex_session_id,
            user_query=query,
            agent_reply=reply_text,
            state_delta={"what_to_pack_briefing": reply_text},
            context_id=context.context_id,
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        log_crewai_run_to_bigquery(
            session_id=vertex_session_id,
            user_id=user_id,
            user_query=query,
            agent_reply=reply_text,
            latency_ms=latency_ms,
        )

        await updater.complete(message=updater.new_agent_message([Part(text=reply_text)]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported for the CrewAI pre_trip_agent.")
