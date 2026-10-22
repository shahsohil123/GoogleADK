"""A2A wrapping for `in_trip_agent` with eager Runner initialization, framework-native
`VertexAiSessionService` session reuse across turns/agents, and OpenTelemetry
`trace_id` / `span_id` propagation.
"""

import os

import httpx
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore
from a2a.types import Task, TaskArtifactUpdateEvent, TaskStatusUpdateEvent
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.executor.config import A2aAgentExecutorConfig, ExecuteInterceptor
from google.adk.a2a import _compat
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.sessions.base_session_service import GetSessionConfig
from opentelemetry import context as otel_context, trace

from in_trip_concierge_agent.agent import root_agent
from in_trip_concierge_agent.card import AGENT_CARD, RPC_PATH
from in_trip_concierge_agent.runner import RUNNER
from in_trip_concierge_agent.user_context import _TracePropagationMiddleware, wire_user_id_header
from in_trip_concierge_agent.vertex_services import (
    current_traceparent,
    extract_otel_context_from_traceparent,
)

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


class _SessionReusingA2aAgentExecutor(A2aAgentExecutor):
    """Subclasses ADK's `A2aAgentExecutor` to:
    1. Attach the caller's OpenTelemetry `traceparent` (from A2A `message.metadata`
       or HTTP headers) so `invocation` and `invoke_agent` spans inherit the
       upstream `trace_id` and `parent_span_id`.
    2. Reuse the user's existing session in `VertexAiSessionService` via
       `get_session` -> `list_sessions(user_id=user_id)` -> `create_session`,
       preventing duplicate session creation for the same `user_id`.
    """

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        tp = None
        if context.message and getattr(context.message, "metadata", None):
            tp = _compat.metadata_get(context.message.metadata, "traceparent")
        if not tp:
            tp = current_traceparent.get() or None

        extracted_ctx = extract_otel_context_from_traceparent(tp)
        if extracted_ctx is not None:
            current_traceparent.set(tp or "")
            active_sc = trace.get_current_span().get_span_context()
            target_sc = trace.get_current_span(extracted_ctx).get_span_context()
            # Only attach extracted_ctx if the ambient span is not already a local
            # recording span in the same trace (e.g. DefaultRequestHandlerV2.on_message_send).
            if not (
                active_sc
                and active_sc.is_valid
                and not active_sc.is_remote
                and active_sc.trace_id == target_sc.trace_id
            ):
                token = otel_context.attach(extracted_ctx)
                try:
                    await super().execute(context, event_queue)
                finally:
                    otel_context.detach(token)
                return

        await super().execute(context, event_queue)

    async def _prepare_session(
        self,
        context: RequestContext,
        run_request,
        runner,
    ):
        session_id = run_request.session_id
        user_id = run_request.user_id
        session = None

        if session_id:
            try:
                session = await runner.session_service.get_session(
                    app_name=runner.app_name,
                    user_id=user_id,
                    session_id=session_id,
                    config=GetSessionConfig(num_recent_events=0),
                )
            except Exception:
                session = None

        if session is None and user_id:
            try:
                listed = await runner.session_service.list_sessions(
                    app_name=runner.app_name,
                    user_id=user_id,
                )
                if listed and listed.sessions:
                    session = listed.sessions[-1]
                    run_request.session_id = session.id
            except Exception:
                session = None

        if session is None:
            try:
                session = await runner.session_service.create_session(
                    app_name=runner.app_name,
                    user_id=user_id,
                    state={},
                    session_id=session_id,
                )
            except Exception:
                session = await runner.session_service.create_session(
                    app_name=runner.app_name,
                    user_id=user_id,
                    state={},
                )
            run_request.session_id = session.id

        return session


_EXECUTOR_CONFIG = A2aAgentExecutorConfig(
    execute_interceptors=[ExecuteInterceptor(after_event=_send_push_notification)]
)
_AGENT_EXECUTOR = _SessionReusingA2aAgentExecutor(
    runner=RUNNER,
    config=_EXECUTOR_CONFIG,
)


def _agent_executor_factory(runner) -> A2aAgentExecutor:
    return _AGENT_EXECUTOR


app = to_a2a(
    root_agent,
    runner=RUNNER,
    agent_card=AGENT_CARD,
    rpc_path=RPC_PATH,
    push_config_store=_push_config_store,
    agent_executor_factory=_agent_executor_factory,
    lifespan=wire_user_id_header,
    port=int(os.environ.get("PORT", "8006")),
)
app.add_middleware(_TracePropagationMiddleware)


from starlette.responses import JSONResponse
from starlette.routing import Route


async def _root_agent_card(_request):
    return JSONResponse(
        AGENT_CARD
        if isinstance(AGENT_CARD, dict)
        else _compat.a2a_to_dict(AGENT_CARD)
    )


for _wk_path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
    app.router.routes.append(Route(_wk_path, _root_agent_card, methods=["GET"]))
