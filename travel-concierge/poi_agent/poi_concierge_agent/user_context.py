"""Lets a caller pin ADK's derived `user_id` via an `X-User-Id` header."""

from contextlib import asynccontextmanager

from a2a.auth.user import User
from a2a.server.routes.common import DefaultServerCallContextBuilder
from starlette.applications import Starlette


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
        user_id = request.headers.get("x-user-id")
        return _HeaderUser(user_id) if user_id else super().build_user(request)


@asynccontextmanager
async def wire_user_id_header(app: Starlette):
    for route in app.routes:
        dispatcher = getattr(route.endpoint, "__self__", None)
        if hasattr(dispatcher, "_context_builder"):
            dispatcher._context_builder = _HeaderUserContextBuilder()
    yield
