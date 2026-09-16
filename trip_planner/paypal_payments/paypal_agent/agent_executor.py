"""A2A `AgentExecutor` that drives the LangGraph ReAct graph in `graph.py`.

The A2A task's `context_id` doubles as the LangGraph thread id, so a
checkpointer keeps each A2A conversation's order/capture ids in scope
across turns.
"""
from langgraph.checkpoint.memory import MemorySaver

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus

from paypal_agent.graph import build_graph


class PayPalAgentExecutor(AgentExecutor):
    def __init__(self):
        self._graph = build_graph(checkpointer=MemorySaver())

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input()
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if not context.current_task:
            # a2a-sdk 1.x removed the new_task() helper — the first event for
            # a new task must be a full Task object, not just a status update.
            await event_queue.enqueue_event(
                Task(
                    id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                )
            )
        await updater.start_work()

        config = {"configurable": {"thread_id": context.context_id}}
        result = await self._graph.ainvoke({"messages": [("user", query)]}, config)
        # The ReAct loop can end on a turn with no text content (the model
        # occasionally returns an empty final message) — never hand that
        # straight to a caller as a silent blank response.
        reply_text = result["messages"][-1].text or (
            "The payments agent finished the request but returned no reply text."
        )

        await updater.complete(message=updater.new_agent_message([Part(text=reply_text)]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported for the PayPal payments agent.")
