"""PayPal's own tools, loaded from its hosted Sandbox MCP server at
`mcp.sandbox.paypal.com` (via SSE — streamable-HTTP 404s on this host).
Auth is an OAuth2 client-credentials token, using PayPal credentials stored
in GCP Secret Manager.
"""
import asyncio
import os

from google.cloud import secretmanager
from langchain_mcp_adapters.client import MultiServerMCPClient
import requests

_DEFAULT_PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"
_MCP_URL = os.environ.get("PAYPAL_MCP_URL", "https://mcp.sandbox.paypal.com/sse")

# Scoped to the create/capture/refund flow this demo exercises, out of
# PayPal's full ~30-tool catalog (invoicing, subscriptions, disputes,
# shipping, merchant insights, ...).
_TOOL_NAMES = {"create_order", "get_order", "pay_order", "create_refund", "get_refund", "list_transactions"}


_secrets_client = secretmanager.SecretManagerServiceClient()


def _read_secret(secret_id: str) -> str:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    name = f"projects/{project}/secrets/{secret_id}/versions/latest"
    return _secrets_client.access_secret_version(name=name).payload.data.decode("utf-8")


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

    return tool.model_copy(update={"coroutine": validated_call})


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
    return [_require_item_descriptions(t) if t.name == "create_order" else t for t in tools]


ALL_TOOLS = asyncio.run(_load_tools())
