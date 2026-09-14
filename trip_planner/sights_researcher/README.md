# Sights Researcher

> An **ADK** agent, exposed over Google's **A2A protocol**, that researches
> places to see at a destination — personalised to the traveler's own
> dietary restrictions and interests, remembered across trips via **Vertex
> AI Agent Engine's Memory Bank**.

![framework](https://img.shields.io/badge/framework-ADK-4285F4) ![protocol](https://img.shields.io/badge/protocol-A2A-34A853) ![model](https://img.shields.io/badge/model-Gemini%203.8%20Flash-FBBC04)

---

## What this demonstrates

- **Personalised research, not a generic top-10 list.** The same
  `load_web_page` research step as [`travel_concierge`](../../travel_concierge)'s
  `researcher` — fetching Wikipedia/Wikitravel/Wikivoyage — but attractions
  and food are filtered and explained against the traveler's own tastes.
- **Preferences that persist across sessions, not a local file.**
  `travel_concierge`'s `preferences_reader` reads a static `user_profile.md`.
  This agent instead reads and writes durable facts (vegetarian? loves
  museums? avoids nightlife?) through **Vertex AI Agent Engine's Memory
  Bank** — Google's managed, semantically-searchable memory store for
  agents, scoped per user and independent of any one conversation.
- **Conversational, not a form or a guesser.** Missing preferences *and*
  missing trip logistics (dates, origin, budget) are asked for one
  natural round at a time and the agent waits for the reply — it never
  fills a gap with a "reasonable default" (a currency, a date, a traveler
  count) just to keep going. See `agent.py`'s instruction.
- **Grounded in live data, not just a static wiki page.** Beyond
  `load_web_page`, `travel_apis.py` wires in real APIs — live flight fares
  (Duffel), current + forecast weather (OpenWeatherMap), rated
  attractions/restaurants (Google Places), live currency conversion
  (open.er-api.com), and a driving-eligibility reference lookup (side of
  the road, minimum age, International Driving Permit requirement) used to
  decide whether a rental car is even worth suggesting. Every one of these
  degrades gracefully — `{"available": false, "reason": ...}` — when its
  key isn't configured, so the agent falls back to research/its own
  knowledge instead of failing. Hotel and rental-car *pricing* isn't
  live-integrated (see below) — those are estimated the same way.
- **An ADK agent exposed over A2A with one call.** `google.adk.a2a.utils.to_a2a()`
  wraps a plain ADK `Agent` as a full A2A Starlette app — no hand-rolled
  `AgentExecutor` needed (contrast with [`paypal_payments`](../paypal_payments),
  which is LangGraph and *does* need one, since A2A's ADK integration is
  ADK-specific).

---

## The scenario

> *"I'm planning a trip to Kyoto."*

1. **First time**: the agent finds nothing in Memory Bank for this user, so
   it asks — "Any dietary restrictions? What kind of attractions do you
   enjoy?" The user answers ("vegetarian, love temples and history, not
   into nightlife"). The agent saves each fact to Memory Bank, then
   researches Kyoto and returns temples, museums, and vegetarian-friendly
   food — explicitly explaining why each pick fits, and leaving out
   nightlife and meat-centric spots.
2. **Next trip, weeks later**: *"What about Osaka?"* — same user, new A2A
   session. `recall_preferences` finds the saved facts immediately; the
   agent skips the questions and goes straight to tailored research.

---

## Architecture

```
┌────────────────────── Any A2A client (ADK, LangGraph, custom) ───────────┐
│   GET  /.well-known/agent-card.json   POST /  (message/send)             │
└───────────────────────────────│─────────────────────────────────────────┘
                                 │  A2A (JSON-RPC over HTTP)
                                 ▼
┌── Process: `uvicorn sights_researcher_agent.a2a_app:app` ─────────────────┐
│  Starlette app from to_a2a(root_agent, runner=create_runner)             │
│      │                                                                   │
│      ▼                                                                   │
│  ADK Runner (runner.py)                                                  │
│      session_service  = VertexAiSessionService(...)   — durable history  │
│      memory_service   = VertexAiMemoryBankService(...) — cross-session   │
│      │                                                                   │
│      ▼                                                                   │
│  sights_researcher agent (Gemini + tools)                                │
│      tools: load_web_page, recall_preferences, save_preference,         │
│             search_places, get_weather_forecast, search_flights,        │
│             get_exchange_rate, get_driving_requirements                 │
│      │                    │                       │                     │
│      ▼                    ▼                       ▼                     │
│  Wikipedia / Wikitravel / Vertex AI Agent Engine   Live APIs             │
│  Wikivoyage (research)    Memory Bank              (travel_apis.py):     │
│                           (SESSION/MEMORY_          Duffel, OpenWeather,│
│                            AGENT_ENGINE_ID)          Google Places,     │
│                                                       open.er-api.com   │
└──────────────────────────────────────────────────────────────────────────┘
```

**Live API keys are read from Secret Manager, not env vars.** `config.py`
fetches `duffel-api-key`, `openweather-api-key`, and `google-places-api-key`
from GCP Secret Manager on first use and caches them in-process — the
matching env var (`DUFFEL_API_KEY`, etc.) is honored only as a local-dev
override, and is never passed to the deployed container. The runtime
identity the BYOC container actually runs as needs
`roles/secretmanager.secretAccessor` on each secret — for a `deploy_byoc.py`
deployment with no `service_account` override, that's the Reasoning Engine
service agent (`service-{PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com`),
**not** the default compute service account.

`recall_preferences`/`save_preference` (`tools.py`) don't call the Memory
Bank API directly — they go through ADK's `ToolContext.search_memory()` /
`ToolContext.add_memory()`, which delegate to whatever `memory_service` the
Runner was built with. That indirection is what let this go from "no
memory" to "Memory Bank" by changing only `runner.py`, with no change to
the tools or the agent's instruction.

**Memory Bank and Session Service need an Agent Engine resource to live
under, but not a deployment.** Each is namespaced under its own
`reasoningEngines/{id}` resource — that's a property of those APIs, not of
where the agent's compute runs. [`../create_session_storage.py`](../create_session_storage.py)
and [`../create_memory_bank.py`](../create_memory_bank.py) create those
resources with no agent attached (a "lightweight instance that can't be
queried" per the SDK's own docs), purely so both services have somewhere
to store records. Both are created once at the `trip_planner/` level and
shared by every ADK agent in this repo — they're namespaced further within
each by `app_name`/`user_id`, so there's no need for one pair per agent.

This holds for the Agent Engine deployment (Option 3) too — `runner.py`'s
`create_runner()` runs unchanged inside the BYOC container, so a deployed
instance persists to these same two shared resources rather than
accumulating its own.

---

## Prerequisites

- **Python 3.12**
- A GCP project with the Vertex AI API enabled, and ADC set up:
  ```bash
  gcloud auth application-default login
  gcloud auth application-default set-quota-project <project>
  ```

---

## Setup

```bash
cd trip_planner
cp .env.example .env && make install
make create-session-storage && make create-memory-bank   # one-time, shared across agents

cd sights_researcher
cp .env.example .env      # fill in GOOGLE_CLOUD_PROJECT + the two ids printed above
make install
```

**Optional — live-data tools** (`travel_apis.py`): each degrades gracefully
if skipped, so none of this is required to run the agent.

- **Flights** (Duffel): sign up at [app.duffel.com/join](https://app.duffel.com/join)
  → Developers → Access tokens → New token (`duffel_test_...`, free sandbox,
  unlimited test balance).
- **Weather** (OpenWeatherMap): free key at [openweathermap.org/api](https://openweathermap.org/api)
  — can take 10–15 min to activate after signup.
- **Attractions/restaurants** (Google Places API (New)): enable it in Cloud
  Console for your project (needs billing attached, though usage stays free
  under 10k calls/month) and create a restricted API key.

Store each as a Secret Manager secret (`duffel-api-key`,
`openweather-api-key`, `google-places-api-key`) and grant
`roles/secretmanager.secretAccessor` on each to the runtime identity the
deployed container will actually use (see Architecture, above) — or just
set the matching env var in `.env` for local-only testing.

---

## Running it

### Option 1 — A2A service (with real Memory Bank persistence)

```bash
make start
```

```bash
curl http://localhost:8003/.well-known/agent-card.json | jq
```

Any A2A client can drive it from that card. Preferences persist per
`user_id` — over plain HTTP without auth, ADK derives a per-`context_id`
pseudo-user (`A2A_USER_<context_id>`), so **reuse the same A2A `context_id`
across sessions** to get the "remembers me" behavior in the scenario above.
An A2A client authenticating with a stable username gets real cross-session
persistence with no special handling.

### Option 2 — ADK dev UI (no Memory Bank)

```bash
make playground
```

Opens ADK's local web UI against the agent directly. This bypasses `to_a2a`
and `runner.py` entirely, so it uses ADK's own in-memory session *and*
memory services — useful for iterating on the research/personalisation
prompt, but preferences won't actually persist here. Use Option 1 to see
real memory recall across sessions.

### Option 3 — Vertex AI Agent Engine, BYOC (managed deployment, real A2A)

Agent Engine's pickle-based deployment template (`AdkApp`) only exposes its
own `query`/`stream_query` interface, not A2A — there's no way to attach
arbitrary HTTP routes to it. **Bring Your Own Container (BYOC)** is Agent
Engine's other deployment mode: it runs an arbitrary container image and
forwards HTTP requests at `{engine}/api/**` to that container, stripping
the `/api` prefix — so the exact same `a2a_app.py` Starlette app the local
A2A service runs (Option 1) can be deployed here unchanged, and clients
reach it over real A2A JSON-RPC.

One-time setup, since this needs somewhere to push the container image:

```bash
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com
gcloud artifacts repositories create trip-planner-agents \
  --repository-format=docker --location=us-central1

PROJECT_NUMBER=$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format='value(projectNumber)')
gcloud artifacts repositories add-iam-policy-binding trip-planner-agents \
  --location=us-central1 \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"
```

Then build and deploy:

```bash
make build-image   # gcloud builds submit -> trip-planner-agents/sights-researcher-a2a:v1
make deploy        # python deploy_byoc.py -> Agent Engine, container_spec + agent_framework="custom"
```

`deploy_byoc.py` passes `SESSION_AGENT_ENGINE_ID`/`MEMORY_AGENT_ENGINE_ID`
via `env_vars`, so the deployed container's `runner.py` persists to the
same two shared resources as the local A2A service — nothing self-wires to
a resource of its own here, since BYOC has no such default to override
(unlike the pickle-based template).

**The agent card's advertised URL matters.** `card.py` computes it based on
whether `GOOGLE_CLOUD_AGENT_ENGINE_ID` is set (only true once actually
running on Agent Engine): locally it's `http://localhost:8003/a2a`; deployed,
it's the passthrough URL below. `a2a_app.py` passes this card and
`rpc_path="/a2a"` into `to_a2a()` so the app's real routes and its
advertised address agree.

Call the deployed agent card and send it a message:

```bash
TOKEN=$(gcloud auth print-access-token)
ENGINE="projects/.../locations/us-central1/reasoningEngines/..."  # from deploy output
A2A="https://us-central1-aiplatform.googleapis.com/reasoningEngines/v1/$ENGINE/api/a2a"

curl -s -H "Authorization: Bearer $TOKEN" "$A2A/.well-known/agent-card.json"

curl -s -X POST "$A2A" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send",
       "params":{"message":{"messageId":"m1","role":"user",
                 "parts":[{"kind":"text","text":"Trip to Lisbon, what should I see?"}]}}}'
```

`gemini-3.8-flash` isn't served from every Vertex AI region — it 404s from
`us-central1` in some projects (where the shared resources above live),
but works from Vertex's `global` endpoint. `agent.py` pins the LLM call
there explicitly via `Gemini(model=..., client_kwargs={"location":
"global"})`, independent of `GOOGLE_CLOUD_LOCATION` used for Session
Service/Memory Bank elsewhere — so the same model config runs unchanged
locally and once deployed. Override `SIGHTS_RESEARCHER_MODEL` if your
project needs a different model.

---

## Project structure

```
sights_researcher/
├── sights_researcher_agent/
│   ├── __init__.py          # exports root_agent (what `adk web` picks up)
│   ├── agent.py               # Plain Agent definition — no A2A wrapping
│   ├── card.py                 # AgentCard, with a URL that switches between localhost and the Agent Engine passthrough
│   ├── a2a_app.py                # to_a2a() app — run locally (Option 1) or containerized for BYOC (Option 3)
│   ├── tools.py                    # recall_preferences / save_preference, via ToolContext
│   ├── travel_apis.py                # Live-data tools: flights, weather, places, currency, driving requirements
│   ├── config.py                       # API keys — fetched from Secret Manager, cached in-process
│   ├── vertex_services.py           # build_session_service / build_memory_service — the shared resources, used by runner.py
│   └── runner.py                     # Runner wired to the shared resources, used both locally and inside the BYOC container
├── Dockerfile                # Builds the BYOC image (Option 3)
├── deploy_byoc.py            # Deploys that image to Vertex AI Agent Engine
├── Makefile                  # install / playground / start / build-image / deploy
├── requirements.txt
├── .env.example
└── README.md
```

---

## Next steps

- **Consolidate on save.** `save_preference` already passes
  `custom_metadata={"enable_consolidation": True}`, which asks Memory Bank
  to merge/de-dupe against existing facts server-side rather than piling up
  near-duplicates over time.
- **Auto-capture the whole conversation.** For facts the user mentions in
  passing without the agent explicitly calling `save_preference`, add an
  `after_agent_callback` that calls `ctx.add_session_to_memory()` to let
  Memory Bank extract facts from the full transcript instead of relying
  only on explicit tool calls.
- **Hand off to `travel_concierge`.** This agent's tailored findings are a
  drop-in replacement for `travel_concierge`'s `research_findings` state key
  — swap its `researcher` `AgentTool` for a remote `RemoteA2aAgent` pointed
  at this service.
