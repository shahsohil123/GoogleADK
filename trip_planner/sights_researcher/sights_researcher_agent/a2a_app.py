"""A2A wrapping for `root_agent`. Run locally with
`uvicorn sights_researcher_agent.a2a_app:app` (`make start`), or deployed to
Agent Engine as a BYOC container by `deploy_byoc.py`.

See trip_planning_agent/a2a_app.py for why this uses a custom
`agent_executor_factory` on top of `to_a2a()` — it wires real
push-notification *delivery*, which `to_a2a()` alone doesn't support (it
only wires the config-registration half, never a sender).
"""

import os

import httpx
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore
from a2a.types import Task, TaskArtifactUpdateEvent, TaskStatusUpdateEvent
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.executor.config import A2aAgentExecutorConfig, ExecuteInterceptor
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from sights_researcher_agent.agent import root_agent
from sights_researcher_agent.card import AGENT_CARD, RPC_PATH
from sights_researcher_agent.runner import create_runner
from sights_researcher_agent.user_context import wire_user_id_header

_push_config_store = InMemoryPushNotificationConfigStore()
_push_sender = BasePushNotificationSender(
    httpx_client=httpx.AsyncClient(),
    config_store=_push_config_store,
)


async def _send_push_notification(executor_context, a2a_event, event):
    """Manually triggers push delivery for each outgoing A2A event — see
    trip_planning_agent/a2a_app.py for the full explanation."""
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
    lifespan=wire_user_id_header,
    port=int(os.environ.get("PORT", "8003")),
)
