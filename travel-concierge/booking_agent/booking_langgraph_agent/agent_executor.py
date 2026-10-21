"""A2A `AgentExecutor` that drives the LangGraph ReAct graph in `graph.py`,
persisting conversation sessions and state in `InMemory` (local mode) or the
shared Vertex AI Session Service (`SESSION_AGENT_ENGINE_ID`) and Memory Bank
(`MEMORY_AGENT_ENGINE_ID`), and streaming analytics to BigQuery for Looker.
"""

import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from langgraph.checkpoint.memory import MemorySaver

from booking_langgraph_agent.graph import build_graph
from booking_langgraph_agent.tools import _RESERVATIONS
from booking_langgraph_agent.vertex_services import (
    append_vertex_session_turn,
    current_user_id,
    load_or_create_vertex_session,
    log_langgraph_run_to_bigquery,
)


def _extract_user_id(context: RequestContext) -> str:
    call_ctx = getattr(context, "call_context", None)
    user = getattr(call_ctx, "user", None) if call_ctx else None
    user_name = getattr(user, "user_name", None) if user else None
    return user_name or f"A2A_USER_{context.context_id}"


class BookingAgentExecutor(AgentExecutor):
    def __init__(self):
        self._graph = build_graph(checkpointer=MemorySaver())
        self._hydrated_contexts: set[str] = set()

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

        vertex_session_id, prior_messages, _ = await load_or_create_vertex_session(
            context.context_id, user_id
        )

        input_messages: list[tuple[str, str]] = []
        if context.context_id not in self._hydrated_contexts and prior_messages:
            input_messages.extend(prior_messages)
        self._hydrated_contexts.add(context.context_id)
        input_messages.append(("user", query))

        config = {"configurable": {"thread_id": context.context_id}}
        result = await self._graph.ainvoke({"messages": input_messages}, config)
        reply_text = result["messages"][-1].text or (
            "The booking agent finished the request but returned no reply text."
        )

        await append_vertex_session_turn(
            session_id=vertex_session_id,
            user_query=query,
            agent_reply=reply_text,
            state_delta={"reservations": dict(_RESERVATIONS)},
            context_id=context.context_id,
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        log_langgraph_run_to_bigquery(
            session_id=vertex_session_id,
            user_id=user_id,
            user_query=query,
            agent_reply=reply_text,
            latency_ms=latency_ms,
        )

        await updater.complete(message=updater.new_agent_message([Part(text=reply_text)]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported for the booking agent.")
