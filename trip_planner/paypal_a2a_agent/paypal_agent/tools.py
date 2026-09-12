"""PayPal's own tools, loaded from its hosted Sandbox MCP server.

PayPal publishes an MCP server at `mcp.sandbox.paypal.com` covering orders,
refunds, invoicing, subscriptions, and more — so instead of hand-rolling
REST wrappers, this agent binds directly to PayPal's tool implementations.

Only streamable-HTTP and SSE transports are documented; streamable-HTTP
(`/http`) 404s against the sandbox host, so this uses SSE (`/sse`), which
works. Auth is an OAuth2 client-credentials bearer token, fetched with
PayPal credentials stored in GCP Secret Manager (same project as Vertex AI).
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from google.cloud import secretmanager
from langchain_mcp_adapters.client import MultiServerMCPClient
import requests

_DEFAULT_PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"
_MCP_URL = os.environ.get("PAYPAL_MCP_URL", "https://mcp.sandbox.paypal.com/sse")

# Scoped to the create/capture/refund flow this demo exercises, out of
# PayPal's full ~30-tool catalog (invoicing, subscriptions, disputes,
# shipping, merchant insights, ...).
_TOOL_NAMES = {"create_order", "get_order", "pay_order", "create_refund", "get_refund", "list_transactions"}


def _read_secret(secret_id: str) -> str:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode("utf-8")


# list_transactions needs PayPal's Transaction Search scope, but PayPal only
# grants it if a token request explicitly asks for it — asking for a scope at
# all drops every scope not listed, so this must be requested alongside the
# app's default scopes rather than in a separate token, since every tool here
# shares one token.
_REPORTING_SCOPE = "https://uri.paypal.com/services/reporting/search/read"


def _get_access_token() -> str:
    base_url = os.environ.get("PAYPAL_BASE_URL", _DEFAULT_PAYPAL_BASE_URL).rstrip("/")
    auth = (_read_secret("paypal-client-id"), _read_secret("paypal-client-secret"))

    default_scopes = requests.post(
        f"{base_url}/v1/oauth2/token",
        auth=auth,
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=15,
    ).json()["scope"]

    resp = requests.post(
        f"{base_url}/v1/oauth2/token",
        auth=auth,
        data={"grant_type": "client_credentials", "scope": f"{default_scopes} {_REPORTING_SCOPE}"},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _require_item_descriptions(tool):
    """Reject a create_order call where an item has no description, instead
    of silently booking something list_transactions can't later identify."""
    call = tool.coroutine

    async def validated_call(**kwargs):
        missing = [item.get("name", "<unnamed item>") for item in kwargs.get("items") or [] if not (item.get("description") or "").strip()]
        if missing:
            return (
                "Error: every item needs a description of what it's for "
                f"(e.g. \"Flight from JFK to LAX\"). Missing for: {', '.join(missing)}.",
                None,
            )
        return await call(**kwargs)

    tool.coroutine = validated_call
    return tool


async def _load_tools():
    client = MultiServerMCPClient(
        {
            "paypal": {
                "url": _MCP_URL,
                "transport": "sse",
                "headers": {"Authorization": f"Bearer {_get_access_token()}"},
            }
        }
    )
    tools = [t for t in await client.get_tools() if t.name in _TOOL_NAMES]
    for t in tools:
        if t.name == "create_order":
            _require_item_descriptions(t)
    return tools


def _run_sync(coro):
    """Run an async one-off to completion, even if called from inside an
    already-running event loop (e.g. Vertex AI Agent Engine's async runtime
    calling `set_up()`) — plain `asyncio.run()` raises in that case."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()


ALL_TOOLS = _run_sync(_load_tools())
