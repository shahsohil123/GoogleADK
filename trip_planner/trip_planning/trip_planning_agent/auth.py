"""A shared, authenticated httpx client for calling the other two agents'
Agent Engine BYOC endpoints (`reasoningEngines/v1/.../api/...`) — unlike a
plain public URL, these require a Google Cloud OAuth bearer token on every
request, including the initial agent-card fetch.
"""

import httpx
import google.auth
import google.auth.transport.requests

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class _GoogleAuth(httpx.Auth):
    def __init__(self):
        self._creds, _ = google.auth.default(scopes=_SCOPES)
        self._request = google.auth.transport.requests.Request()

    def auth_flow(self, request):
        if not self._creds.valid:
            self._creds.refresh(self._request)
        request.headers["Authorization"] = f"Bearer {self._creds.token}"
        yield request


def build_authed_httpx_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(auth=_GoogleAuth(), timeout=120.0)
