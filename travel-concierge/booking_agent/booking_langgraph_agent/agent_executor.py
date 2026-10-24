"""A2A `AgentExecutor` that drives the LangGraph ReAct graph in `graph.py`,
persisting conversation sessions and state in `InMemory` (local mode) or the
shared Vertex AI Session Service (`SESSION_AGENT_ENGINE_ID`) and Memory Bank
(`MEMORY_AGENT_ENGINE_ID`), and streaming analytics with correlated OpenTelemetry
`trace_id` and `span_id` to BigQuery for Looker.
"""

import asyncio
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from langgraph.checkpoint.memory import MemorySaver
from opentelemetry import context as otel_context, trace

from booking_langgraph_agent.graph import build_graph
from booking_langgraph_agent.tools import _RESERVATIONS
from booking_langgraph_agent.vertex_services import (
    append_vertex_session_turn,
    current_traceparent,
    current_user_id,
    extract_otel_context_from_traceparent,
    load_or_create_vertex_session,
    log_langgraph_run_to_bigquery,
)

_tracer = trace.get_tracer("travel_concierge.booking_agent")


def _extract_user_id(context: RequestContext) -> str:
    call_ctx = getattr(context, "call_context", None)
    user = getattr(call_ctx, "user", None) if call_ctx else None
    user_name = getattr(user, "user_name", None) if user else None
    return user_name or f"A2A_USER_{context.context_id}"


async def _persist_turn_async(
    context_id: str,
    user_id: str,
    query: str,
    reply_text: str,
    state_delta: dict,
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
            state_delta=state_delta,
            context_id=context_id,
            user_id=user_id,
        )
    except Exception:
        pass
    try:
        await asyncio.to_thread(
            log_langgraph_run_to_bigquery,
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


class BookingAgentExecutor(AgentExecutor):
    def __init__(self):
        self._graph = build_graph(checkpointer=MemorySaver())

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
            with _tracer.start_as_current_span("invoke_agent booking_agent") as span:
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
                input_messages: list[tuple[str, str]] = []
                session_state: dict = {}
                try:
                    resolved_session_id, prior_messages, session_state = await load_or_create_vertex_session(
                        context.context_id, user_id
                    )
                except Exception:
                    prior_messages = []
                    session_state = {}

                if isinstance(session_state.get("reservations"), dict):
                    _RESERVATIONS.update(session_state["reservations"])

                span.set_attribute("gen_ai.agent.name", "booking_agent")
                span.set_attribute("gen_ai.conversation.id", resolved_session_id)
                span.set_attribute("adk.user_id", user_id)

                config = {"configurable": {"thread_id": resolved_session_id}}
                existing_state = await self._graph.aget_state(config)
                if (not existing_state or not existing_state.values.get("messages")) and prior_messages:
                    input_messages.extend(prior_messages[-6:])
                input_messages.append(("user", query))

                result = await self._graph.ainvoke({"messages": input_messages}, config)
                reply_text = result["messages"][-1].text or (
                    "The booking agent finished the request but returned no reply text."
                )

                latency_ms = int((time.monotonic() - t0) * 1000)
                asyncio.create_task(
                    _persist_turn_async(
                        context_id=resolved_session_id,
                        user_id=user_id,
                        query=query,
                        reply_text=reply_text,
                        state_delta={"reservations": dict(_RESERVATIONS)},
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
        raise NotImplementedError("Cancellation is not supported for the booking agent.")
