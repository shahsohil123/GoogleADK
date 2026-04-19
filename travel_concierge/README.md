# AI Travel Concierge

> A small, readable reference for **human-in-the-loop**, **long-running
> workflows**, and **reflect-and-retry** in **[Google ADK](https://adk.dev)**
> — a multi-agent travel planner that plans a trip *one day at a time*,
> pausing after each day to wait for your approval in plain English.

![framework](https://img.shields.io/badge/framework-Google%20ADK-4285F4) ![model](https://img.shields.io/badge/model-Gemini%203%20Flash-34A853) ![deploy](https://img.shields.io/badge/deploys%20to-Vertex%20AI%20Agent%20Engine-FBBC04)

📹 **Demo video:** [`resources/Agent Development Kit Dev UI - 18 April 2026.mp4`](resources/Agent%20Development%20Kit%20Dev%20UI%20-%2018%20April%202026.mp4)
— a walk-through of the dev UI running the full scenario end-to-end.

---

## What this demonstrates

- **Human-in-the-loop without UI widgets.** Every day of the itinerary,
  and the final booking, is gated by plain-text approval (*"approve"*,
  *"book it"*). No `require_confirmation=True` dialogs, no custom
  front-end — works in any chat surface (Slack, SMS, dev UI, a phone
  call).
- **Long-running, interruptible workflows.** The itinerary is planned
  one day at a time. The agent happily pauses across minutes, hours,
  or days while it waits for you. Session state carries the plan,
  approvals, and research forward so the agent can resume exactly
  where it left off.
- **Reflect-and-retry on failing tools.** The bundled
  `mock_booking_mcp/` shows an async MCP booking flow with a 20%
  random failure rate; ADK's `ReflectAndRetryToolPlugin` detects the
  failure, lets the LLM reflect on the root cause, and retries with an
  adapted strategy.

Supporting patterns along for the ride:

| Pattern | How it shows up |
|---|---|
| **Multi-agent orchestration** | A root coordinator delegates to three specialist agents (`AgentTool` + `sub_agent`). |
| **Tool use** | Built-in `load_web_page` for research plus custom `FunctionTool`s for reading profile files and recording approvals. |
| **Cross-agent state** | The coordinator stashes research + preferences in session state so the itinerary builder can pick them up when control transfers. |
| **MCP integration** | A local stdio MCP server (`mock_booking_mcp/`) exposes `submit_booking` and `check_booking_status` to the itinerary builder. |
| **Production deployment** | One-command deploy to **Vertex AI Agent Engine**, which preserves session state so a paused trip can be resumed later. |

---

## The scenario

> *"Plan a 3-day trip to Tokyo for 2 people, budget $3000"*

1. **Coordinator** reads your request.
2. **Preferences Reader** fetches your profile from local files
   (*vegetarian, loves street food, light packer…*).
3. **Researcher** fetches Tokyo from Wikipedia / Wikitravel / Wikivoyage
   and pulls out attractions, neighbourhoods, food, costs, and
   practical tips.
4. Control transfers to the **Itinerary Builder**, which writes out
   Day 1 in full — timed slots, specific restaurants, costs, transport
   — and then stops.
5. You reply *"approve"* (or tell it what to change). The builder
   revises or moves on to Day 2.
6. After the last day, it shows the full plan and waits for a
   *"book it"*. Then it submits via the mock booking MCP, polls until
   the job completes (retrying on failure), and saves the itinerary to
   disk.

---

## Architecture

```
               "Plan a 3-day trip to Tokyo…"
                          │
                          ▼
               ┌──────────────────────┐
               │  travel_concierge    │  (root coordinator)
               │  Gemini 3 Flash      │
               └──┬───────┬──────────┬┘
       AgentTool  │       │ AgentTool│ sub_agent (transfer)
                  ▼       ▼          ▼
         ┌──────────┐ ┌─────────────┐ ┌──────────────────┐
         │researcher│ │preferences_ │ │ itinerary_       │
         │          │ │reader       │ │ builder          │
         │ load_web_│ │ read_user_  │ │ record_day_      │
         │ page     │ │ profile     │ │ approval,        │
         │          │ │ read_past_  │ │ record_final_    │
         │          │ │ trips       │ │ booking,         │
         │          │ │             │ │ save_itinerary,  │
         │          │ │             │ │ booking_mcp ───► │──▶ submit_booking()
         └──────────┘ └─────────────┘ └──────────────────┘     check_booking_status()
                                                               (stdio MCP subprocess)
```

### Meet the agents

| Agent | Wired as | Tools | Job |
|---|---|---|---|
| `travel_concierge` | root `Agent` | (none directly) | Orchestrator. Runs preferences → research, then transfers. |
| `researcher` | `AgentTool` | `load_web_page` | Pulls destination info from reliable wiki sources. |
| `preferences_reader` | `AgentTool` | `read_user_profile`, `read_past_trips` | Reads markdown profile + trip history from `resources/`. |
| `itinerary_builder` | `sub_agent` | approval + booking tools + `booking_mcp` | Plans day by day, books via MCP, persists final plan. |

**Why a mix of `AgentTool` and `sub_agent`?**
Research and preferences are one-shot lookups that return clean results
— `AgentTool` keeps control with the coordinator. The itinerary builder
needs a long, multi-turn conversation with the human, so it takes full
control via `sub_agent` transfer.

---

## Prerequisites

- **Python 3.12** — `brew install python@3.12`
- **Google Cloud project** with `aiplatform.googleapis.com` enabled
- **`gcloud` CLI** authenticated:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```

The model is **Gemini 3 Flash on Vertex AI**. The code sets
`GOOGLE_GENAI_USE_VERTEXAI=true` automatically; you just need a
project.

> **Prefer AI Studio?** Set `GOOGLE_GENAI_USE_VERTEXAI=false` and
> `GOOGLE_API_KEY=<your key>` in `.env` and remove the
> `os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"` line in
> `agent/agent.py`.

---

## Setup

```bash
cd travel_concierge
cp .env.example .env                 # then edit GOOGLE_CLOUD_PROJECT
make install
```

`.env` minimum:

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=<your-gcp-project>
GOOGLE_CLOUD_LOCATION=us-central1
```

---

## Running it

### Option 1 — ADK dev UI (recommended for a demo)

```bash
make playground     # .venv/bin/adk web .
```

Open the printed URL (usually <http://localhost:8000>), pick
**`travel_concierge`**, and type the scenario prompt.

### Option 2 — Interactive CLI

```bash
source .venv/bin/activate
python run.py
```

### Option 3 — One-shot query

```bash
python run.py --query "Plan a 2-day trip to Kyoto for 2 people, budget $1500"
```

### Option 4 — Straight `adk run`

```bash
make run            # .venv/bin/adk run agent/
```

### Demo walk-through

1. Start the dev UI: `make playground`.
2. Ask: *"Plan a 3-day trip to Tokyo for 2 people, budget $3000"*.
3. Watch the agents pick up the baton — preferences reader surfaces
   *"vegetarian, loves street food"*, researcher pulls Tokyo highlights,
   coordinator transfers to the itinerary builder.
4. **Day 1** appears in full. Reply *"approve"* — or nudge it
   (*"swap ramen for something vegetarian"*). It revises and re-asks.
5. Repeat for Day 2 and Day 3.
6. The full plan is shown. Reply *"book it"*.
7. The itinerary is saved as `resources/itinerary_tokyo_japan.md`.

---

## Mock Booking MCP integration

The project includes a **local stdio MCP server** at `mock_booking_mcp/`
that simulates async flight booking so you can exercise polling +
reflect-and-retry end-to-end without a real booking API.

### What it provides

- `submit_booking(flight_id, passengers)` — returns a `job_id`.
- `check_booking_status(job_id)` — returns `pending` →
  `processing (N%)` → `completed` or `failed`.
- 4-5 second processing, 20% random failure rate.

### Quick test (no agent)

```bash
cd mock_booking_mcp
make setup-env
make demo
```

### Wiring it into the agent

1. **Enable the retry plugin** in `run.py`:

```python
from google.adk.plugins import ReflectAndRetryToolPlugin
app = App(
    name="travel_concierge",
    root_agent=root_agent,
    plugins=[ReflectAndRetryToolPlugin(max_retries=3)],
)
```

2. **Add the MCP toolset** in `agent/agent.py`:

```python
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from pathlib import Path

booking_server_path = str(
    Path(__file__).parent.parent / "mock_booking_mcp" / "server.py"
)
booking_mcp = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="python3",
            args=[booking_server_path],
        ),
    ),
)
# add booking_mcp to itinerary_builder.tools
```

When the user says *"book it"*, the agent calls `submit_booking`,
polls `check_booking_status`, and — when a failure comes back — the
plugin reflects on the error and retries with an adapted strategy.

---

## Deploying to Vertex AI Agent Engine

### One command

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
make deploy
```

### Full options

```bash
python deployment/deploy.py --project my-proj --region us-central1   # create
python deployment/deploy.py --update                                 # update
python deployment/deploy.py --test                                   # smoke-test
python deployment/deploy.py --delete                                 # tear down
```

### Alternative: ADK CLI

```bash
adk deploy agent_engine \
  --project=YOUR_PROJECT \
  --region=us-central1 \
  agent/
```

---

## Project structure

```
travel_concierge/
├── agent/
│   ├── __init__.py             # exports root_agent (what adk web picks up)
│   ├── agent.py                # coordinator + 3 specialist agents
│   └── tools.py                # approval / booking / file tools
├── deployment/
│   └── deploy.py               # Agent Engine create/update/test/delete
├── resources/
│   ├── user_profile.md         # sample traveler profile (read by preferences_reader)
│   ├── past_trips.md           # sample trip history
│   └── Agent Development Kit Dev UI - 18 April 2026.mp4   # demo recording
├── mock_booking_mcp/           # stdio MCP server — async job polling + retry
│   ├── server.py               # submit_booking / check_booking_status
│   ├── demo.py                 # standalone polling demo
│   ├── Makefile                # setup-env / install / run / demo
│   └── .env.example
├── run.py                      # CLI entry point
├── Makefile                    # install / playground / run / deploy / clean
├── requirements.txt
├── .env.example
└── README.md
```

---

## Key patterns

### 1. Coordinator that mixes `AgentTool` with `sub_agent`

```python
root_agent = Agent(
    name="travel_concierge",
    model="gemini-3-flash-preview",
    instruction="""Step 1 — preferences_reader. Step 2 — researcher.
    Step 3 — transfer to itinerary_builder.""",
    tools=[
        AgentTool(create_researcher()),
        AgentTool(create_preferences_reader()),
    ],
    sub_agents=[
        create_itinerary_builder(),      # full control hand-off
    ],
)
```

### 2. Plain-text human-in-the-loop

```python
# agent/tools.py
async def record_day_approval(day_number: int, tool_context: ToolContext) -> dict:
    approved = tool_context.state.get("approved_days", [])
    approved.append({"day": day_number, "status": "approved"})
    tool_context.state["approved_days"] = approved
    tool_context.state["current_day"] = day_number + 1
    return {"status": "approved"}

approve_day_tool = FunctionTool(record_day_approval)    # no confirmation dialog
```

The itinerary builder's system instruction teaches it to call
`record_day_approval` only *after* the user types "approve" in chat.
The tool has no side-effect outside session state, so the model can
call it freely.

### 3. State that travels with the conversation

```python
tool_context.state["user_preferences"] = summary          # stored by coordinator
tool_context.state["research_findings"] = research_output # stored by coordinator
# itinerary_builder reads both when it starts planning
```

### 4. Factory functions for sub-agents

Every specialist is built by a `create_*()` function. ADK will
complain if you share an agent instance across two parents, so calling
the factory each time you wire up the graph avoids that class of bug.

---

## Next steps

- **Wire to a real booking API.** Swap the `mock_booking_mcp/` server
  for Amadeus, Booking.com, or a corporate-travel API. The agent code
  stays the same — same `submit_booking` / `check_booking_status`
  contract, same polling loop, same retry plugin.
- **Swap Wikipedia research for a real MCP toolset.** Drop the Fetch
  MCP server into the researcher and let the LLM pick the best URL
  instead of a hand-written list. Same idea for a filesystem MCP
  replacing the `read_user_profile` / `read_past_trips` tools.
- **Add persistent memory.** A memory-MCP or ADK memory service can
  turn each trip into long-term knowledge: *"last time in Japan you
  hated the early-morning fish market — shall I skip Tsukiji?"*
- **Move the approval onto another channel.** Because approvals are
  plain text, you can route the itinerary builder's output through
  Slack or SMS and let the user approve from their phone without
  changing any ADK code.

---

## License & disclaimers

Demo code — no real bookings are made. Web fetches are read-only
research from public wiki sources. Budget figures are model estimates;
always double-check for actual travel.
