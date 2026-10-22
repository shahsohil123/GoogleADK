"""A2A `AgentExecutor` that drives the CrewAI `pre_trip_agent` Crew, backed by
`InMemory` (local mode) or the shared Vertex AI Session Service
(`SESSION_AGENT_ENGINE_ID`) and Memory Bank (`MEMORY_AGENT_ENGINE_ID`), and
streaming analytics with correlated OpenTelemetry `trace_id` and `span_id` to
BigQuery for Looker.
"""

import asyncio
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from opentelemetry import context as otel_context, trace

from pre_trip_crewai_agent.vertex_services import (
    append_vertex_session_turn,
    current_traceparent,
    current_user_id,
    extract_otel_context_from_traceparent,
    load_or_create_vertex_session,
    log_crewai_run_to_bigquery,
    search_memory_facts_sync,
)
from pre_trip_crewai_agent.crew import build_pre_trip_crew

_tracer = trace.get_tracer("travel_concierge.pre_trip_agent")


def _extract_user_id(context: RequestContext) -> str:
    call_ctx = getattr(context, "call_context", None)
    user = getattr(call_ctx, "user", None) if call_ctx else None
    user_name = getattr(user, "user_name", None) if user else None
    return user_name or f"A2A_USER_{context.context_id}"


async def _persist_crew_turn_async(
    context_id: str,
    user_id: str,
    query: str,
    reply_text: str,
    latency_ms: int,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
) -> None:
    try:
        current_user_id.set(user_id)
        await append_vertex_session_turn(
            session_id=context_id,
            user_query=query,
            agent_reply=reply_text,
            state_delta={"what_to_pack_briefing": reply_text},
            context_id=context_id,
            user_id=user_id,
        )
    except Exception:
        pass
    try:
        await asyncio.to_thread(
            log_crewai_run_to_bigquery,
            session_id=context_id,
            user_id=user_id,
            user_query=query,
            agent_reply=reply_text,
            latency_ms=latency_ms,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
        )
    except Exception:
        pass


class PreTripAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        t0 = time.monotonic()
        query = context.get_user_input()
        user_id = _extract_user_id(context)
        current_user_id.set(user_id)

        tp = None
        md = getattr(context.message, "metadata", None) if context.message else None
        if md:
            try:
                tp = md["traceparent"] if "traceparent" in md else None
            except Exception:
                tp = md.get("traceparent") if hasattr(md, "get") else None
        if not tp:
            tp = current_traceparent.get() or None

        parent_span_id = None
        if tp and len(tp.split("-")) >= 4:
            parent_span_id = tp.split("-")[2]

        extracted_ctx = extract_otel_context_from_traceparent(tp)
        token = None
        if extracted_ctx is not None:
            active_sc = trace.get_current_span().get_span_context()
            target_sc = trace.get_current_span(extracted_ctx).get_span_context()
            if not (
                active_sc
                and active_sc.is_valid
                and not active_sc.is_remote
                and active_sc.trace_id == target_sc.trace_id
            ):
                token = otel_context.attach(extracted_ctx)

        try:
            with _tracer.start_as_current_span("invoke_agent pre_trip_agent") as span:
                sc = span.get_span_context()
                trace_id_hex = f"{sc.trace_id:032x}" if sc and sc.is_valid else None
                span_id_hex = f"{sc.span_id:016x}" if sc and sc.is_valid else None

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

                resolved_session_id = context.context_id
                history_lines: list[str] = []
                try:
                    resolved_session_id, history_lines, _ = await load_or_create_vertex_session(
                        context.context_id, user_id
                    )
                except Exception:
                    history_lines = []
                history_str = "\n".join(history_lines[-6:]) if history_lines else "None"

                span.set_attribute("gen_ai.agent.name", "pre_trip_agent")
                span.set_attribute("gen_ai.conversation.id", resolved_session_id)
                span.set_attribute("adk.user_id", user_id)

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

                latency_ms = int((time.monotonic() - t0) * 1000)
                asyncio.create_task(
                    _persist_crew_turn_async(
                        context_id=resolved_session_id,
                        user_id=user_id,
                        query=query,
                        reply_text=reply_text,
                        latency_ms=latency_ms,
                        trace_id=trace_id_hex,
                        span_id=span_id_hex,
                        parent_span_id=parent_span_id,
                    )
                )

                await updater.complete(message=updater.new_agent_message([Part(text=reply_text)]))
        finally:
            if token is not None:
                otel_context.detach(token)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported for the CrewAI pre_trip_agent.")
