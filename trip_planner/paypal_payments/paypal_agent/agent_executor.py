"""A2A `AgentExecutor` that drives the LangGraph ReAct graph in `graph.py`.

The A2A task's `context_id` doubles as the LangGraph thread id, so a
checkpointer keeps each A2A conversation's order/capture ids in scope
across turns.
"""
from langgraph.checkpoint.memory import MemorySaver

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState
from a2a.utils import new_agent_text_message, new_task

from paypal_agent.graph import build_graph


class PayPalAgentExecutor(AgentExecutor):
    def __init__(self):
        self._graph = build_graph(checkpointer=MemorySaver())

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input()
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        config = {"configurable": {"thread_id": task.context_id}}
        result = await self._graph.ainvoke({"messages": [("user", query)]}, config)
        reply_text = result["messages"][-1].text

        await updater.update_status(
            TaskState.completed,
            new_agent_text_message(reply_text, task.context_id, task.id),
            final=True,
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation is not supported for the PayPal payments agent.")
