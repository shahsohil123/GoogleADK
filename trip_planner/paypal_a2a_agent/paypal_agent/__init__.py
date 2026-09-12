"""LangGraph-side agent package — the remote PayPal Payments service.

This package is exposed as a standalone A2A HTTP service via uvicorn; it
is NOT intended to be loaded as an in-process ADK agent (the `adk web`
dev UI will not discover it because no `root_agent` is re-exported here).
Import `paypal_agent.agent:app` for uvicorn.
"""
