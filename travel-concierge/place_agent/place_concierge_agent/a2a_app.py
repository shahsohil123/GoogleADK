"""A2A wrapping for `root_agent`."""

import os

import httpx
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore
from a2a.types import Task, TaskArtifactUpdateEvent, TaskStatusUpdateEvent
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.executor.config import A2aAgentExecutorConfig, ExecuteInterceptor
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from place_concierge_agent.agent import root_agent
from place_concierge_agent.card import AGENT_CARD, RPC_PATH
from place_concierge_agent.runner import create_runner
from place_concierge_agent.user_context import wire_user_id_header

_push_config_store = InMemoryPushNotificationConfigStore()
_push_sender = BasePushNotificationSender(
    httpx_client=httpx.AsyncClient(),
    config_store=_push_config_store,
)


async def _send_push_notification(executor_context, a2a_event, event):
    if isinstance(a2a_event, Task):
        task_id = a2a_event.id
    elif isinstance(a2a_event, (TaskStatusUpdateEvent, TaskArtifactUpdateEvent)):
        task_id = a2a_event.task_id
    else:
        return a2a_event

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
    port=int(os.environ.get("PORT", "8008")),
)


from starlette.responses import JSONResponse
from starlette.routing import Route

async def _root_agent_card(_request):
    return JSONResponse(AGENT_CARD if isinstance(AGENT_CARD, dict) else AGENT_CARD.model_dump(mode="json", by_alias=True, exclude_none=True))

for _wk_path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
    app.router.routes.append(Route(_wk_path, _root_agent_card, methods=["GET"]))
