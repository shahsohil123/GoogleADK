"""API keys for the live travel-data tools in `travel_apis.py`, read from GCP
Secret Manager and cached in-process. All optional — each tool reports
itself unavailable if its key can't be resolved. Each corresponding env var
(DUFFEL_API_KEY, OPENWEATHER_API_KEY, GOOGLE_PLACES_API_KEY) is still
honored as a local-dev override, skipping the Secret Manager round-trip."""

import os

_cache: dict[str, str | None] = {}
_secrets_client = None


def _secret(secret_id: str, env_override: str) -> str | None:
    if secret_id in _cache:
        return _cache[secret_id]

    value = os.environ.get(env_override)
    if not value:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if project:
            try:
                global _secrets_client
                from google.cloud import secretmanager

                if _secrets_client is None:
                    _secrets_client = secretmanager.SecretManagerServiceClient()
                name = f"projects/{project}/secrets/{secret_id}/versions/latest"
                value = _secrets_client.access_secret_version(name=name).payload.data.decode("utf-8")
            except Exception:
                value = None

    _cache[secret_id] = value
    return value


def duffel_api_key() -> str | None:
    return _secret("duffel-api-key", "DUFFEL_API_KEY")


def openweather_api_key() -> str | None:
    return _secret("openweather-api-key", "OPENWEATHER_API_KEY")


def google_places_api_key() -> str | None:
    return _secret("google-places-api-key", "GOOGLE_PLACES_API_KEY")
