"""HTTPX client for calling other A2A agents.

- **Local / Docker Mode (`LOCAL_MODE=true`)**: Statelessly forwards only the
  active traveler's `X-User-Id` header — makes zero Google Cloud Auth calls.
- **Cloud Mode (`LOCAL_MODE=false`)**: Attaches both the Google Cloud OAuth
  bearer token and `X-User-Id` header for Vertex AI Agent Engine endpoints.
"""

from contextvars import ContextVar
import os

import httpx
from inspiration_concierge_agent.vertex_services import is_local_mode

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
current_user_id: ContextVar[str] = ContextVar("current_user_id", default="default_traveler")


class _HybridA2AAuth(httpx.Auth):
    def __init__(self):
        self._creds = None
        self._request = None

    def _ensure_gcp_creds(self):
        if self._creds is None:
            import google.auth
            import google.auth.transport.requests

            self._creds, _ = google.auth.default(scopes=_SCOPES)
            self._request = google.auth.transport.requests.Request()

    def auth_flow(self, request: httpx.Request):
        url_str = str(request.url)
        if "global-aiplatform.googleapis.com" in url_str and "/locations/global/reasoningEngines/" in url_str:
            eng_loc = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
            fixed_url = url_str.replace(
                "global-aiplatform.googleapis.com", f"{eng_loc}-aiplatform.googleapis.com"
            ).replace("/locations/global/reasoningEngines/", f"/locations/{eng_loc}/reasoningEngines/")
            request.url = httpx.URL(fixed_url)
        request.headers["X-User-Id"] = current_user_id.get()
        # Only attach Google Cloud OAuth token when calling Cloud endpoints in non-local mode
        host = (request.url.host or "").lower()
        is_cloud_host = host.endswith(".googleapis.com") or host.endswith(".run.app")
        if not is_local_mode() and is_cloud_host:
            self._ensure_gcp_creds()
            if not self._creds.valid:
                self._creds.refresh(self._request)
            request.headers["Authorization"] = f"Bearer {self._creds.token}"
        yield request


def build_authed_httpx_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(auth=_HybridA2AAuth(), timeout=240.0)
