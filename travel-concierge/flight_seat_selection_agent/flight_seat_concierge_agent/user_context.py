"""Lets a caller pin ADK's derived `user_id` via an `X-User-Id` header and
propagates incoming OpenTelemetry `traceparent` / `X-Traceparent` headers so
distributed A2A calls share the same `trace_id` and `parent_span_id`.
"""

from contextlib import asynccontextmanager

from a2a.auth.user import User
from a2a.server.routes.common import DefaultServerCallContextBuilder
from opentelemetry import context as otel_context
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware

from flight_seat_concierge_agent.vertex_services import (
    current_traceparent,
    extract_otel_context_from_traceparent,
)


class _HeaderUser(User):
    def __init__(self, user_name: str):
        self._user_name = user_name

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return self._user_name


class _HeaderUserContextBuilder(DefaultServerCallContextBuilder):
    def build_user(self, request):
        tp = request.headers.get("x-traceparent")
        if tp:
            current_traceparent.set(tp)
        user_id = request.headers.get("x-user-id")
        return _HeaderUser(user_id) if user_id else super().build_user(request)


class _TracePropagationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Only honor explicit X-Traceparent from upstream A2A agents; ignore
        # GFE-injected traceparent headers whose proxy span IDs are not in Cloud Trace.
        tp = request.headers.get("x-traceparent")
        current_traceparent.set(tp or "")
        if tp:
            extracted_ctx = extract_otel_context_from_traceparent(tp)
            if extracted_ctx is not None:
                token = otel_context.attach(extracted_ctx)
                try:
                    return await call_next(request)
                finally:
                    otel_context.detach(token)
        return await call_next(request)


@asynccontextmanager
async def wire_user_id_header(app: Starlette):
    for route in app.routes:
        dispatcher = getattr(route.endpoint, "__self__", None)
        if hasattr(dispatcher, "_context_builder"):
            dispatcher._context_builder = _HeaderUserContextBuilder()
        handler = getattr(dispatcher, "request_handler", None)
        executor = getattr(handler, "agent_executor", None)
        if executor is not None and hasattr(executor, "_resolve_runner"):
            try:
                runner = await executor._resolve_runner()
                for plugin in getattr(runner.plugin_manager, "plugins", []):
                    if hasattr(plugin, "_ensure_started"):
                        await plugin._ensure_started()
            except Exception:
                pass
    yield
