# AI Shopping Concierge — ADK ↔ LangGraph over A2A

> A minimal, runnable demo of **two agent frameworks collaborating over
> Google's [A2A protocol](https://github.com/google-a2a/A2A)** — an ADK
> front-of-house agent calling a LangGraph back-end agent across
> processes with zero shared code.

![framework](https://img.shields.io/badge/frameworks-ADK%20%2B%20LangGraph-4285F4) ![protocol](https://img.shields.io/badge/protocol-A2A-34A853) ![model](https://img.shields.io/badge/model-Gemini%202.5%20Flash-FBBC04)

---

## What this demonstrates

- **Multi-framework collaboration via A2A.** A Google ADK agent and a
  LangGraph `StateGraph` run in separate processes, built with different
  stacks, and talk only through the A2A protocol — no shared imports.
- **Agent Card discovery.** The shopper reads the researcher's card at
  `/.well-known/agent-card.json` to discover its name, skills, and RPC
  endpoint. The card is the entire integration contract.
- **Right tool for each job.** ADK `Agent` handles conversation and
  session state; LangGraph `StateGraph` handles deterministic,
  checkpointable multi-step research. They cooperate without either
  team rewriting the other's work.

---

## The scenario

> *"I travel a lot for work and want noise-cancelling headphones under
> $300 that are comfortable on 10-hour flights. What should I get?"*

1. You type the brief into the ADK dev UI at `http://localhost:8000`.
2. The **Personal Shopper** (ADK) decides it needs product research
   and calls its `product_researcher` tool over A2A.
3. The **Product Researcher** (LangGraph) runs two nodes:
   - `find_candidates` pulls a shortlist.
   - `compare_and_rank` weighs them against the brief.
4. The ranked shortlist returns over A2A.
5. The Personal Shopper streams back a warm recommendation: top pick,
   runner-up, and what to skip.

---

## Architecture

```
╔══════════ Your browser: http://localhost:8000 (adk web dev UI) ══════════╗
║                                                                          ║
║   "I want noise-cancelling headphones under $300..."                     ║
║                              │                                           ║
╚══════════════════════════════│═══════════════════════════════════════════╝
                               │
┌──────────────────── Process 1: `adk web adk_shopper` ────────────────────┐
│                                                                          │
│   ADK Runner (loaded from adk_shopper/personal_shopper/agent.py)         │
│      │                                                                   │
│      ▼                                                                   │
│   ┌─────────────────────────────┐                                        │
│   │  personal_shopper           │   model: gemini-2.5-flash              │
│   │  (google.adk.Agent)         │                                        │
│   └─────────────────────────────┘                                        │
│      │                                                                   │
│      │  tools=[ AgentTool(remote_researcher) ]                           │
│      ▼                                                                   │
│   ┌─────────────────────────────┐                                        │
│   │  remote_researcher          │   RemoteA2aAgent                       │
│   │  (A2A client)               │   agent_card = <RESEARCHER_URL>/.well- │
│   └─────────────────────────────┘                  known/agent-card.json │
│                     │                                                    │
└─────────────────────┼────────────────────────────────────────────────────┘
                      │
                      │   A2A  (JSON-RPC over HTTP)
                      │   1. GET  /.well-known/agent-card.json
                      │   2. POST /  (message/send)
                      ▼
┌── Process 2: `uvicorn langgraph_researcher.product_researcher:app` ──────┐
│                                                                          │
│   Starlette app produced by `to_a2a(root_agent, ...)`                    │
│      │                                                                   │
│      ▼                                                                   │
│   ┌─────────────────────────────┐                                        │
│   │  product_researcher         │   google.adk.agents.LangGraphAgent     │
│   │  (LangGraphAgent wrapper)   │                                        │
│   └─────────────────────────────┘                                        │
│      │                                                                   │
│      ▼                                                                   │
│      LangGraph StateGraph  (compiled with MemorySaver checkpointer)      │
│                                                                          │
│         START ──▶ find_candidates ──▶ compare_and_rank ──▶ END           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Why two frameworks?

| Concern | Best tool |
|---|---|
| Conversational front-end with a user | **ADK `Agent`** — LLM reasoning, tools, session management, dev UI |
| Deterministic multi-step research | **LangGraph `StateGraph`** — explicit nodes, checkpointable |
| Letting them talk across processes | **A2A protocol** — discovery via Agent Card + JSON-RPC |

---

## Prerequisites

- **Python 3.12**
- One of these auth setups (put in `.env`, loaded automatically):
  - `GOOGLE_API_KEY` (AI Studio) with `GOOGLE_GENAI_USE_VERTEXAI=false`
  - `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` with
    `GOOGLE_GENAI_USE_VERTEXAI=true` and
    `gcloud auth application-default login`

---

## Setup

```bash
cd a2a_demo
cp .env.example .env          # fill in your Google credentials
make install                  # create .venv and install deps
```

---

## Running it

You need two terminals — the researcher is a separate process.

### Option 1 — Default ports

**Terminal 1 — LangGraph researcher (A2A server on :8001)**
```bash
make start-researcher
```

**Terminal 2 — ADK dev UI (on :8000)**
```bash
make run-shopper
```

Open the URL `adk web` prints (usually <http://localhost:8000>), select
`personal_shopper`, and type the scenario prompt.

### Option 2 — Custom ports

```bash
# terminal 1
RESEARCHER_HOST=127.0.0.1 RESEARCHER_PORT=9001 \
  .venv/bin/uvicorn langgraph_researcher.product_researcher:app \
  --host 127.0.0.1 --port 9001

# terminal 2
RESEARCHER_URL=http://127.0.0.1:9001 .venv/bin/adk web adk_shopper --port 8888
```

> `RESEARCHER_HOST`/`RESEARCHER_PORT` must match the uvicorn bind —
> those values are baked into the agent card's `url` field that
> clients call back on.

### Peek at the agent card

```bash
curl http://localhost:8001/.well-known/agent-card.json | jq
```

You'll see the researcher introduce itself: name, description, skills,
preferred transport, RPC URL. That card is the *only* contract the
shopper needs to integrate.

---

## Project structure

```
a2a_demo/
├── adk_shopper/                           # ADK side (the `adk web` target)
│   └── personal_shopper/                  # one ADK agent lives here
│       ├── __init__.py                    # re-exports .agent so adk discovers it
│       └── agent.py                       # defines `root_agent`
├── langgraph_researcher/                  # LangGraph side (a remote A2A service)
│   ├── __init__.py
│   └── product_researcher.py              # StateGraph + `to_a2a()` Starlette app
├── Makefile                               # install / start-researcher / run-shopper
├── requirements.txt                       # google-adk[a2a], langgraph, uvicorn
├── .env.example
└── README.md
```

The directory separation is deliberate: `adk_shopper/` is an **agents
directory** that `adk web` discovers, while `langgraph_researcher/` is
a **service package** run by uvicorn. The two sides never import each
other.

---

## Key patterns

### 1. Publishing an agent as an A2A service

```python
# langgraph_researcher/product_researcher.py
from google.adk.a2a.utils.agent_to_a2a import to_a2a

app = to_a2a(root_agent, host=HOST, port=PORT)
```

`to_a2a()` returns a Starlette app. It auto-builds the agent card from
the ADK agent's `name` + `description`, publishes it at
`/.well-known/agent-card.json`, and mounts JSON-RPC routes. No
hand-written card or routing code needed.

### 2. Consuming a remote agent as a tool

```python
# adk_shopper/personal_shopper/agent.py
from google.adk.agents import RemoteA2aAgent
from google.adk.tools import AgentTool

remote_researcher = RemoteA2aAgent(
    agent_card=f"{RESEARCHER_URL}/.well-known/agent-card.json",
)

root_agent = Agent(
    name="personal_shopper",
    tools=[AgentTool(remote_researcher)],
)
```

Wrapping the remote agent in **`AgentTool`** (rather than `sub_agents`)
keeps control with the shopper so it can synthesize a final,
human-friendly reply. `sub_agents` would hand off execution entirely.

### 3. LangGraph checkpointer is required

```python
graph = workflow.compile(checkpointer=MemorySaver())
```

`LangGraphAgent` invokes the graph with a thread id per session, so
the compiled graph needs a checkpointer. Without it you get
`"No checkpointer set"`.

---

## Troubleshooting

**`ImportError: cannot import CompiledGraph from langgraph.graph.graph`**
ADK still imports `CompiledGraph` from the removed module
`langgraph.graph.graph`. `product_researcher.py` restores that import
path with a tiny module shim — make sure the shim runs before any
`langgraph_agent` import.

**Shopper calls the researcher but gets no response**
Check that `RESEARCHER_URL` (shopper side) matches the uvicorn bind
(researcher side). The card's `url` field must be reachable from the
shopper process.

---

## Next steps

- **Swap the hard-coded candidates** in `find_candidates_node` for a
  real product feed — Google Shopping, Amazon PA-API, Shopify, or a
  vector store of product reviews.
- **Add a third agent** — a CrewAI *price-tracker* or a LlamaIndex
  *reviews summariser* — also exposed via `to_a2a()`. Drop another
  `RemoteA2aAgent` into the shopper's tools list.
- **Deploy the researcher to Cloud Run** and point `RESEARCHER_URL` at
  the public URL. No code change on either side — the card handles
  discovery.
- **Add more agents under `adk_shopper/`** (e.g. a `returns_concierge/`)
  — they'll automatically appear in the `adk web` dropdown.
