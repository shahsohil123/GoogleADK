"""A2A wrapping for `root_agent`. Run locally with
`uvicorn trip_planning_agent.a2a_app:app` (`make start`), or deployed to
Agent Engine as a BYOC container by `deploy_byoc.py`.

Uses ADK's `to_a2a()` (the standard way to expose an ADK agent over A2A) with
a custom `agent_executor_factory` to also wire real push-notification
*delivery* — a capability `to_a2a()` doesn't provide out of the box. It only
ever wires a push-notification *config* store (so a client can
register/list/delete a webhook via `push_config_store=`); nothing in
`to_a2a()` or the ADK internals it calls
(`google.adk.a2a._compat.attach_a2a_routes_to_app`) ever constructs or wires
a `PushNotificationSender`, so without this, a registered webhook would
never actually receive anything. `A2aAgentExecutorConfig.execute_interceptors`
is the extension point ADK exposes for this (marked `@a2a_experimental` in
ADK's own source, so treat this as relying on an evolving API).
"""

import os

import httpx
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore
from a2a.types import Task, TaskArtifactUpdateEvent, TaskStatusUpdateEvent
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.executor.config import A2aAgentExecutorConfig, ExecuteInterceptor
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from trip_planning_agent.agent import root_agent
from trip_planning_agent.card import AGENT_CARD, RPC_PATH
from trip_planning_agent.runner import create_runner

_push_config_store = InMemoryPushNotificationConfigStore()
_push_sender = BasePushNotificationSender(
    httpx_client=httpx.AsyncClient(),
    config_store=_push_config_store,
)


async def _send_push_notification(executor_context, a2a_event, event):
    """Manually triggers push delivery for each outgoing A2A event.

    Mirrors what a2a-sdk's own DefaultRequestHandler/active_task machinery
    does automatically when a push_sender is wired directly into it (see
    a2a.server.agent_execution.active_task._update_task_state) — this
    interceptor exists only because to_a2a() gives no way to wire that
    push_sender in through its normal path.
    """
    if isinstance(a2a_event, Task):
        task_id = a2a_event.id
    elif isinstance(a2a_event, (TaskStatusUpdateEvent, TaskArtifactUpdateEvent)):
        task_id = a2a_event.task_id
    else:
        return a2a_event  # Message — not a push-notifiable event type.

    await _push_sender.send_notification(task_id, a2a_event)
    return a2a_event


def _agent_executor_factory(runner) -> A2aAgentExecutor:
    return A2aAgentExecutor(
        runner=runner,
        config=A2aAgentExecutorConfig(
            execute_interceptors=[ExecuteInterceptor(after_event=_send_push_notification)]
        ),
    )


app = to_a2a(
    root_agent,
    runner=create_runner,
    agent_card=AGENT_CARD,
    rpc_path=RPC_PATH,
    push_config_store=_push_config_store,
    agent_executor_factory=_agent_executor_factory,
    port=int(os.environ.get("PORT", "8004")),
)
