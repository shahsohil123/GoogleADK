import warnings

warnings.filterwarnings("ignore")
"""CrewAI pre_trip_agent exposed as an A2A service, wired to the shared
Vertex AI Session Service and Memory Bank.

Run from the `pre_trip_agent/` directory:
    uvicorn pre_trip_crewai_agent.agent:app --host 0.0.0.0 --port 8005
"""

import os

from dotenv import load_dotenv

load_dotenv()

import httpx
from a2a.auth.user import User
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentProvider, AgentSkill
from fastapi import FastAPI
from opentelemetry import context as otel_context
from starlette.middleware.base import BaseHTTPMiddleware

from pre_trip_crewai_agent.agent_executor import PreTripAgentExecutor
from pre_trip_crewai_agent.vertex_services import (
    current_traceparent,
    extract_otel_context_from_traceparent,
)

_HOST = "localhost"
_PORT = int(os.environ.get("PORT", "8005"))


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


def _rpc_url() -> str:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
    engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
    if project and location and engine_id:
        resource = f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"
        return f"https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api/"
    return f"http://{_HOST}:{_PORT}/"


skills = [
    AgentSkill(
        id="pre_trip_readiness",
        name="Pre-Trip Readiness, Advisories, and Packing List",
        description=(
            "Given an upcoming trip itinerary and traveler profile, researches "
            "visa requirements, medical/vaccine requirements, storm/weather updates, "
            "and travel advisories using Google Search grounding, and generates a "
            "tailored packing list (what_to_pack)."
        ),
        tags=["pre-trip", "visa", "medical", "weather", "advisory", "packing", "what-to-pack"],
        examples=[
            "Run pre-trip update for my upcoming San Diego to Seattle itinerary.",
            "What visa, medical requirements, and packing list do I need for this trip?",
        ],
    ),
]

agent_card = AgentCard(
    name="pre_trip_agent",
    description=(
        "Given an itinerary, keeps up to date and provides relevant pre-trip travel "
        "information (visa, medical, storm monitor, travel advisories, and what to pack) "
        "before the trip (built with CrewAI)."
    ),
    supported_interfaces=[
        AgentInterface(url=_rpc_url(), protocol_binding="JSONRPC", protocol_version="1.0")
    ],
    provider=AgentProvider(organization="travel-concierge", url=f"http://{_HOST}:{_PORT}/"),
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=True, push_notifications=True),
    skills=skills,
)

_push_config_store = InMemoryPushNotificationConfigStore()
_push_sender = BasePushNotificationSender(
    httpx_client=httpx.AsyncClient(),
    config_store=_push_config_store,
)

_handler = DefaultRequestHandler(
    agent_executor=PreTripAgentExecutor(),
    task_store=InMemoryTaskStore(),
    push_config_store=_push_config_store,
    push_sender=_push_sender,
    agent_card=agent_card,
)

app = FastAPI()
app.add_middleware(_TracePropagationMiddleware)
add_a2a_routes_to_fastapi(
    app,
    agent_card_routes=create_agent_card_routes(agent_card),
    jsonrpc_routes=create_jsonrpc_routes(
        _handler, rpc_url="/", context_builder=_HeaderUserContextBuilder()
    ) + create_jsonrpc_routes(
        _handler, rpc_url="/a2a", context_builder=_HeaderUserContextBuilder()
    ),
)


from starlette.responses import JSONResponse
from starlette.routing import Route


async def _root_agent_card(_request):
    return JSONResponse(agent_card.model_dump(mode="json", by_alias=True, exclude_none=True))


for _wk_path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
    app.router.routes.append(Route(_wk_path, _root_agent_card, methods=["GET"]))
