# Trip Planner

> A collection of independent agents supporting a trip-planning-as-merchant
> demo — each sub-folder is a fully self-contained project (own venv,
> dependencies, `Makefile`) that runs on its own and talks to the others
> only over the network (A2A), never via shared Python imports.

---

## Agents

- **[`paypal_a2a_agent/`](./paypal_a2a_agent)** — a LangGraph ReAct agent
  managing PayPal Sandbox payment tasks (create/authorize/capture/refund),
  exposed as an A2A service via `a2a-sdk`.

More agents (e.g. a trip-planning orchestrator that drives the PayPal
agent to hold and finalize bookings) will land here as separate
sub-folders, each independently runnable.
