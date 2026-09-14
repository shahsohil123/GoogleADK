# Trip Planner

> A collection of independent agents supporting a trip-planning-as-merchant
> demo — each sub-folder is a fully self-contained project (own venv,
> dependencies, `Makefile`) that runs on its own and talks to the others
> only over the network (A2A), never via shared Python imports.

---

## Agents

- **[`paypal_payments/`](./paypal_payments)** — a LangGraph
  ReAct agent managing PayPal Sandbox payment tasks
  (create/authorize/capture/refund), exposed as an A2A service via
  `a2a-sdk`.
- **[`sights_researcher/`](./sights_researcher)** — an ADK agent that
  researches places to see at a destination, personalised to the
  traveler's preferences via Vertex AI Agent Engine's Memory Bank.

More agents (e.g. a trip-planning orchestrator that drives these agents
to hold and finalize bookings) will land here as separate sub-folders,
each independently runnable.

---

## Shared infrastructure

Two Vertex AI Agent Engine resources back durable state for every ADK
agent in this repo — each namespaced further per-agent by
`app_name`/`user_id`, so one of each covers every agent rather than one
pair each:

- **`trip-planner-shared-state`** — Session Service (durable conversation
  history), created by `create_agent_engine.py session`.
- **`trip-planner-memory-bank`** — Memory Bank (durable, cross-session
  facts), created by `create_agent_engine.py memory`. Kept as a separate
  resource from Session Service so each can be managed independently.

```bash
cd trip_planner
cp .env.example .env         # fill in GOOGLE_CLOUD_PROJECT
make install
make create-session-storage  # one-time — paste SESSION_AGENT_ENGINE_ID into each agent's .env
make create-memory-bank      # one-time — paste MEMORY_AGENT_ENGINE_ID into each agent's .env
```

This is ADK-specific infrastructure — LangGraph agents like
`paypal_payments` manage their own state (a `MemorySaver`
checkpointer) and don't need it.
