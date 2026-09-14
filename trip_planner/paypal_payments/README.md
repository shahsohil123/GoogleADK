# PayPal Payments Agent

> A **LangGraph** ReAct agent, exposed over Google's **A2A protocol**, that
> manages PayPal Sandbox payment tasks — create, capture, check, refund —
> for any A2A client to drive with zero shared code.

![framework](https://img.shields.io/badge/framework-LangGraph-1C3C3C) ![protocol](https://img.shields.io/badge/protocol-A2A-34A853) ![model](https://img.shields.io/badge/model-Gemini%203.7%20Flash-FBBC04)

---

## What this demonstrates

- **A LangGraph agent as a standalone A2A service.** Built directly on
  the official `a2a-sdk` — no framework wrapper required to publish the
  agent card and JSON-RPC routes.
- **Tool-calling against PayPal's own MCP server.** A ReAct loop
  (`create_react_agent`) binds directly to tools hosted by PayPal
  (`mcp.sandbox.paypal.com`) — no hand-rolled REST wrappers — and decides
  which to call from free-text requests ("charge $20 for the order",
  "refund that capture").
- **Session-scoped conversation state.** A `MemorySaver` checkpointer
  lets the agent track order/capture ids mentioned earlier in the same
  A2A session without the caller re-stating them.
- **Three ways to run the same graph.** The exact same `graph.py` runs
  as a standalone A2A service, in LangGraph Studio for step-by-step
  debugging, or as a managed Vertex AI Agent Engine deployment — see
  [Running it](#running-it).

---

## The scenario

> *"Create a $25 order for a yearly subscription, then once it's
> approved, capture it."*

1. An A2A client sends the request to this agent's RPC endpoint.
2. The agent calls `create_order`, returning an order id and a buyer
   approval link.
3. Once the buyer opens that link and approves in the PayPal sandbox,
   the client asks the agent to proceed.
4. The agent calls `pay_order` and reports the captured amount and
   status back over A2A.

---

## Architecture

```
┌────────────────────── Any A2A client (ADK, LangGraph, custom) ───────────┐
│                                                                          │
│   1. GET  /.well-known/agent-card.json  (discover skills + RPC url)      │
│   2. POST /                              (message/send)                 │
│                                                                          │
└───────────────────────────────│─────────────────────────────────────────┘
                                 │  A2A (JSON-RPC over HTTP)
                                 ▼
┌── Process: `uvicorn paypal_agent.agent:app` ─────────────────────────────┐
│                                                                          │
│   Starlette app from A2AStarletteApplication(agent_card, http_handler)   │
│      │                                                                   │
│      ▼                                                                   │
│   ┌─────────────────────────────┐                                        │
│   │  DefaultRequestHandler       │   a2a.server — task lifecycle,        │
│   │  + PayPalAgentExecutor       │   thread id = A2A task context id     │
│   └─────────────────────────────┘                                        │
│      │                                                                   │
│      ▼                                                                   │
│   LangGraph ReAct agent (create_react_agent, MemorySaver checkpointer)   │
│      │  tools: create_order, get_order, pay_order, create_refund,       │
│      │         get_refund, list_transactions                            │
│      ▼                                                                   │
│   langchain-mcp-adapters (SSE)  ──HTTPS──▶  PayPal's hosted MCP server   │
│                                              (mcp.sandbox.paypal.com)    │
└──────────────────────────────────────────────────────────────────────────┘
```

The LLM only ever sees typed tool functions — it never talks to the
PayPal API directly. The tools themselves are PayPal's own implementations,
loaded at startup from PayPal's hosted MCP server and filtered down to the
six this demo exercises (out of ~30 covering invoicing, subscriptions,
disputes, and more): `create_order`, `get_order`, `pay_order`,
`create_refund`, `get_refund`, and `list_transactions`. `tools.py` also
handles the one piece of REST plumbing still needed — fetching the OAuth2
bearer token the MCP server authenticates with — and wraps `create_order`
with a small guard that rejects any line item missing a human-readable
description (e.g. "Flight from JFK to LAX"), since that description is the
only way `list_transactions` can later say what a transaction was for.

---

## Stack

| Component | Role |
|-----------|------|
| **LangGraph** (`create_react_agent`) | Tool-calling loop deciding which PayPal action to take |
| **`a2a-sdk`** | Publishes the graph as an A2A service — agent card, task lifecycle, JSON-RPC routes |
| **PayPal MCP server** (Sandbox, SSE transport) | Hosts the actual tool implementations — orders, captures, refunds |
| **`langchain-mcp-adapters`** | Binds the MCP server's tools as LangChain tools for `create_react_agent` |
| **Gemini** (AI Studio or Vertex AI) | The agent's reasoning LLM |

---

## Prerequisites

- **Python 3.12**

| Credential | Purpose | Free tier |
|---|---|---|
| PayPal sandbox client id/secret | REST app from the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/applications/sandbox) — stored in **GCP Secret Manager** (`paypal-client-id`/`paypal-client-secret`), not `.env` | Yes — sandbox is free |
| `GOOGLE_API_KEY` (AI Studio) **or** `GOOGLE_CLOUD_PROJECT` + ADC (Vertex) | Powers the agent's LLM | Yes, generous free tier either way |

`tools.py` reads the PayPal credentials from Secret Manager in `GOOGLE_CLOUD_PROJECT` and exchanges them for the OAuth2 bearer token used to authenticate to PayPal's MCP server, so that variable is required no matter which LLM backend you pick. Create the two secrets once (see [.env.example](./.env.example) for the exact `gcloud secrets` commands) and grant your ADC identity the `Secret Manager Secret Accessor` role on the project.

`graph.py` picks the LLM backend from `GOOGLE_GENAI_USE_VERTEXAI` — `false` (default) uses AI Studio with `GOOGLE_API_KEY`; `true` uses Vertex AI with `GOOGLE_CLOUD_LOCATION` and your local `gcloud auth application-default login` credentials (run `gcloud auth application-default set-quota-project <project>` too, or both Vertex and Secret Manager calls fail with a `PERMISSION_DENIED` quota-project error).

---

## Setup

```bash
cd trip_planner/paypal_payments
cp .env.example .env      # fill in PayPal sandbox + Google credentials
make install
```

---

## Running it

### Option 1 — A2A service

```bash
make start
```

Peek at the published agent card:

```bash
curl http://localhost:8002/.well-known/agent-card.json | jq
```

Any A2A client — an ADK `RemoteA2aAgent`, another LangGraph agent, or a
raw A2A client — can drive it from that card alone. See
[`a2a_demo`](../../a2a_demo) for a worked example of an ADK agent
consuming a remote LangGraph agent this way.

### Option 2 — LangGraph Studio (dev UI)

LangGraph's equivalent of `adk web`: runs the compiled graph directly
behind a local API server and opens a visual Studio UI where you can
watch nodes execute and inspect state between steps. Note the UI page
itself is hosted at `smith.langchain.com` — only the API server
(`langgraph dev`) runs locally, and your browser talks to it directly.

```bash
make studio
```

This opens LangGraph Studio in your browser, connected to a local
server started from [`langgraph.json`](./langgraph.json), which points
at `paypal_agent/graph.py:graph`. Send it a message like *"Create a $10
order for a book"* and step through the `agent` → `tools` loop to see
each MCP tool call and its result.

> On Safari, `make studio` will fail to connect — Safari blocks Studio's
> page from reaching plain `http://localhost`. Use `make studio-safari`
> instead (adds a Cloudflare tunnel), and if Studio then rejects the
> tunnel's random domain, click **Configure connection** and allow it.

### Option 3 — Vertex AI Agent Engine, BYOC (managed deployment, real A2A)

Agent Engine's prebuilt `LanggraphAgent` template only exposes a
synchronous `query()` (it calls the compiled graph's `.invoke()`), which is
incompatible with PayPal's async-only MCP tools — and even if it weren't,
it (like every pickle-based Agent Engine template, ADK's included) only
exposes Agent Engine's own query/stream_query interface, not A2A; there's
no way to attach arbitrary HTTP routes to it. **Bring Your Own Container
(BYOC)** is Agent Engine's other deployment mode: it runs an arbitrary
container image and forwards HTTP requests at `{engine}/api/**` to that
container, stripping the `/api` prefix — so the exact same
`paypal_agent/agent.py` Starlette app `make start` runs locally can be
deployed here unchanged, reachable over real A2A JSON-RPC. There's no
LangGraph-specific Agent Engine template at all (unlike `AdkApp` for ADK
agents — see [`sights_researcher`](../sights_researcher)), so BYOC is the
only way to run this agent on Agent Engine, period.

One-time setup before the first deploy — a runtime service account (so the
deployed agent can call Secret Manager and Vertex AI, not your own ADC
identity) and a place to push the container image:

```bash
gcloud iam service-accounts create paypal-agent-engine \
  --display-name="PayPal Agent Engine runtime"
gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:paypal-agent-engine@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:paypal-agent-engine@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Shared with sights_researcher — skip if you've already created this:
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
make build-image   # gcloud builds submit -> trip-planner-agents/paypal-payments-a2a:v1
make deploy        # python deploy_byoc.py -> Agent Engine, container_spec + agent_framework="custom"
```

**The agent card's advertised URL matters.** `agent.py`'s `_rpc_url()`
computes it based on whether `GOOGLE_CLOUD_AGENT_ENGINE_ID` is set (only
true once actually running on Agent Engine): locally it's
`http://localhost:8002/`; deployed, it's the passthrough URL below.

Call the deployed agent card and send it a message:

```bash
TOKEN=$(gcloud auth print-access-token)
ENGINE="projects/.../locations/us-central1/reasoningEngines/..."  # from deploy output
A2A="https://us-central1-aiplatform.googleapis.com/reasoningEngines/v1/$ENGINE/api"

curl -s -H "Authorization: Bearer $TOKEN" "$A2A/.well-known/agent-card.json"

curl -s -X POST "$A2A/" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send",
       "params":{"message":{"messageId":"m1","role":"user",
                 "parts":[{"kind":"text","text":"Create a $10 order for a book."}]}}}'
```

---

## Project structure

```
paypal_payments/
├── paypal_agent/
│   ├── __init__.py
│   ├── tools.py               # OAuth2 token fetch + loads PayPal's own tools from its hosted MCP server
│   ├── graph.py               # ReAct graph — loaded directly by LangGraph Studio
│   ├── agent_executor.py      # a2a-sdk AgentExecutor bridging A2A tasks to the graph
│   └── agent.py               # AgentCard + A2AStarletteApplication app — run locally or containerized for BYOC
├── langgraph.json             # LangGraph Studio / CLI manifest
├── Dockerfile                 # Builds the BYOC image (Option 3)
├── deploy_byoc.py             # Deploys that image to Vertex AI Agent Engine
├── Makefile                   # install / start / studio / build-image / deploy / clean
├── requirements.txt
├── .env.example
└── README.md
```

---

## Troubleshooting

**`401` from `/v1/oauth2/token`**
Double-check the `paypal-client-id`/`paypal-client-secret` Secret Manager
values come from a **Sandbox** REST app, not a Live one, and that
`PAYPAL_BASE_URL` still points at `api-m.sandbox.paypal.com`.

**`PermissionDenied: 403 ... Secret Manager Secret Accessor`**
Your ADC identity needs the `roles/secretmanager.secretAccessor` role on
`GOOGLE_CLOUD_PROJECT` (or on the two secrets specifically).

**`404` connecting to the MCP server**
PayPal's docs list both a streamable-HTTP (`/http`) and an SSE (`/sse`)
endpoint. As of writing, `/http` 404s against the sandbox host — `tools.py`
uses `/sse`, which works. If PayPal fixes `/http`, set `PAYPAL_MCP_URL` and
switch `transport` to `"streamable_http"` in `tools.py` if you'd rather use
that.

**`ValueError: No checkpointer set`** (only if you edit `graph.py`)
`build_graph()` (no args) is for LangGraph Studio, which persists state
itself and rejects a pre-attached checkpointer. `PayPalAgentExecutor`
calls `build_graph(checkpointer=MemorySaver())` instead, since it resumes
the graph per A2A session itself.

**`FAILED_PRECONDITION: Environment variable name 'GOOGLE_CLOUD_PROJECT' is reserved`**
Agent Engine injects `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` itself —
don't pass them in `env_vars` in `deploy_byoc.py`.

**`RuntimeError: asyncio.run() cannot be called from a running event loop`**
This is why `tools.py` loads `ALL_TOOLS` through `_run_sync()` instead of a
bare `asyncio.run()` — safe regardless of how this module ends up getting
imported into a process that already has an event loop running.

---

## Next steps

- **Expose more of PayPal's MCP catalog** — invoicing, subscriptions,
  disputes, and shipment tracking are all already available from the same
  server; add their tool names to `_TOOL_NAMES` in `tools.py`.
- **Move to Live credentials** once tested, by swapping `PAYPAL_BASE_URL`
  to `api-m.paypal.com`, `PAYPAL_MCP_URL` to `https://mcp.paypal.com/sse`,
  and using a Live REST app's client id/secret.
