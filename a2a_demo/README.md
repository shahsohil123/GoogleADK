# AI Shopping Concierge — ADK ↔ LangGraph over A2A

A minimal, runnable blog-friendly demo of **two agent frameworks collaborating
over Google's [A2A protocol](https://github.com/google-a2a/A2A)** to solve one
of the most relatable problems on the internet: *"what should I actually buy?"*

- A **Personal Shopper** (Google ADK `Agent`, Gemini 2.5 Flash) talks to the
  customer, understands their brief, and produces the final recommendation.
  You drive it through the built-in `adk web` dev UI in your browser.
- A **Product Researcher** (LangGraph `StateGraph`) runs behind the scenes as
  a remote A2A service — it finds candidate products and ranks them against
  the brief.

The two agents live in different processes, are built with different
frameworks, and never import each other. They only speak A2A: the shopper
reads the researcher's **Agent Card** at `/.well-known/agent-card.json` and
sends tasks over JSON-RPC.

> Why this matters: in a real company the "front-of-house" assistant and the
> specialist back-end agents are often built by different teams with different
> preferred stacks. A2A lets them collaborate without either team rewriting
> the other's work.

---

## The scenario

> *"I travel a lot for work and want noise-cancelling headphones under $300
> that are comfortable on 10-hour flights. What should I get?"*

1. You type the brief into the ADK dev UI at `http://localhost:8000`.
2. The Personal Shopper decides it needs product research and calls its
   `product_researcher` tool over A2A.
3. The LangGraph graph runs two nodes:
   - `find_candidates` — pulls together a shortlist of products.
   - `compare_and_rank` — weighs them against the brief and ranks them.
4. The ranked shortlist returns over A2A.
5. The Personal Shopper streams a warm recommendation back into the dev UI:
   top pick, runner-up, and what to skip.

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

## Project layout

```
a2a_demo/
├── adk_shopper/                           # ADK side (the `adk web` target)
│   └── personal_shopper/                  # one ADK agent lives here
│       ├── __init__.py                    # re-exports .agent so adk discovers it
│       └── agent.py                       # defines `root_agent`
│
├── langgraph_researcher/                  # LangGraph side (a remote A2A service)
│   ├── __init__.py
│   └── product_researcher.py              # StateGraph + `to_a2a()` Starlette app
│
├── Makefile                               # install / start-researcher / run-shopper
├── README.md
├── requirements.txt                       # google-adk[a2a], langgraph, uvicorn
└── .env                                   # Google GenAI credentials
```

The directory separation is deliberate: `adk_shopper/` is an **agents
directory** that `adk web` discovers, while `langgraph_researcher/` is a
**service package** run by uvicorn. The two sides never import each other.

---

## Prerequisites

- Python 3.12
- One of:
  - `GOOGLE_API_KEY` (AI Studio) with `GOOGLE_GENAI_USE_VERTEXAI=false`, or
  - `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` with
    `GOOGLE_GENAI_USE_VERTEXAI=true` and `gcloud auth application-default login`

Put these in `.env` (loaded automatically by ADK).

---

## Running the demo

```bash
make install              # create .venv and install deps

# terminal 1 — start the LangGraph researcher (A2A server on :8001)
make start-researcher

# terminal 2 — start the ADK dev UI (on :8000 by default)
make run-shopper
```

Then open the URL `adk web` prints (usually http://localhost:8000), select
`personal_shopper` from the dropdown, and type the scenario prompt:

> *"I travel a lot for work and want noise-cancelling headphones under $300
> that are comfortable on 10-hour flights. What should I get?"*

You'll watch the shopper think, call the `product_researcher` tool over A2A,
and then stream the final recommendation.

### Custom ports

```bash
# terminal 1
RESEARCHER_HOST=127.0.0.1 RESEARCHER_PORT=9001 \
  .venv/bin/uvicorn langgraph_researcher.product_researcher:app \
  --host 127.0.0.1 --port 9001

# terminal 2
RESEARCHER_URL=http://127.0.0.1:9001 .venv/bin/adk web adk_shopper --port 8888
```

> `RESEARCHER_HOST`/`RESEARCHER_PORT` must match the uvicorn bind — those
> values are baked into the agent card's `url` field that clients call back
> on.

### Peek at the agent card

```bash
curl http://localhost:8001/.well-known/agent-card.json | jq
```

You'll see the researcher introduce itself: name, description, skills,
preferred transport, RPC URL. That card is the *only* contract the shopper
needs to integrate.

---

## Key implementation notes

- **`to_a2a(agent, host, port)`** returns a Starlette app. It auto-builds the
  agent card from the ADK agent's `name` + `description`, publishes it at
  `/.well-known/agent-card.json`, and mounts JSON-RPC routes. No hand-written
  card or routing code needed.
- **`RemoteA2aAgent(agent_card=<card-url>)`** acts as an A2A client. Wrapping
  it in **`AgentTool`** (rather than putting it in `sub_agents`) keeps
  control with the shopper so it can synthesize a final, human-friendly
  reply. `sub_agents` would hand off execution entirely.
- **`adk web` discovery**: `adk web adk_shopper` treats `adk_shopper/` as an
  agents directory and looks for subdirectories with a `root_agent` exposed
  via `__init__.py` or `agent.py`. Here only `personal_shopper/` qualifies,
  so the dropdown is clean.
- **Checkpointer required**: `LangGraphAgent` invokes the graph with a
  thread id per session, so the compiled graph needs `checkpointer=MemorySaver()`
  (or another saver). Without it you get `"No checkpointer set"`.
- **LangGraph ≥1.0 shim**: ADK still imports `CompiledGraph` from the
  removed module `langgraph.graph.graph`. `product_researcher.py` restores
  that import path with a tiny module shim.

---

## Extending the demo

- Replace the hard-coded candidates in `find_candidates_node` with a real
  product feed — Google Shopping, Amazon PA-API, Shopify, or a vector
  store of product reviews.
- Add a third agent — e.g. a CrewAI *price-tracker* or a LlamaIndex
  *reviews summarizer* — also exposed via `to_a2a()`. Drop another
  `RemoteA2aAgent` into the shopper's tools list.
- Deploy the researcher to Cloud Run and point `RESEARCHER_URL` at the
  public URL. No code change on either side — the card handles discovery.
- Add more agents under `adk_shopper/` (e.g. a `returns_concierge/`) —
  they'll automatically appear in the `adk web` dropdown.