"""Deploys sights_researcher to Vertex AI Agent Engine as a Bring-Your-Own-
Container (BYOC) A2A service — an arbitrary container running the same
`a2a_app.py` Starlette app as `make start`, instead of the pickle-based
`AdkApp` deployment in `deploy_agent_engine.py` (which only exposes Agent
Engine's own query/stream_query interface, not A2A).

Build and push the image first:
    gcloud builds submit --tag "$LOCATION-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/trip-planner-agents/sights-researcher-a2a:v1" .

Then deploy (from this directory, after `make install`):
    python deploy_byoc.py                  # updates AGENT_ENGINE_RESOURCE_NAME
                                            # from .env if set, else creates fresh
    python deploy_byoc.py <resource_name>   # redeploy in place, explicit override

On a fresh create, the new resource name is written back into .env as
AGENT_ENGINE_RESOURCE_NAME so the next `deploy_byoc.py` run (with no
argument) updates in place instead of accidentally creating a duplicate
resource — see ./delete_byoc.py, which clears that value again on delete.

Once deployed, the agent card is served at:
    https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api/a2a/.well-known/agent-card.json
"""

import json
import os
import re
import subprocess
import sys
import tempfile

import warnings

import google.auth
import google.auth.transport.requests
import httpx
import vertexai

# vertexai.Client is deprecated in favor of agentplatform.Client, but the
# replacement's runtimes.update() doesn't patch a resource in place — it
# silently deletes and recreates it under a new resource ID (confirmed by
# testing directly against the API), which is unacceptable for a redeploy
# script. Suppressing this specific warning rather than "fixing" it back
# into that unsafe path.
warnings.filterwarnings(
    "ignore", message="The vertexai.Client class is deprecated.*", category=FutureWarning
)
from dotenv import dotenv_values, load_dotenv

load_dotenv(override=True)  # .env on disk always wins over a stale Make-exported value


def _set_env_var(key: str, value: str, path: str = ".env") -> None:
    """Adds or replaces `key=value` in a local .env file, preserving the
    rest of it, so a fresh create's resource name is remembered for the
    next redeploy without a manual copy-paste."""
    line = f"{key}={value}\n"
    existing = open(path).read() if os.path.exists(path) else ""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    updated = pattern.sub(line.rstrip("\n"), existing) if pattern.search(existing) else existing + line
    with open(path, "w") as f:
        f.write(updated)


def _register_a2a_agent(service_id: str, resource_name: str, card_path: str) -> None:
    """Registers/updates this deployment's A2A agent card in Agent Registry.

    Agent Registry's A2A_AGENT entries are NOT auto-derived from the live
    Agent Engine resource the way its CUSTOM query/streamQuery entries are —
    confirmed by observing stale A2A_AGENT entries keep pointing at a
    resource's OLD id after that resource was deleted and recreated. They're
    static records that only exist/update if something explicitly runs
    `gcloud alpha agent-registry services create|update`. Without this, every
    redeploy (which gets a new resource id) would leave the registry
    pointing at a dead URL until someone manually re-registers it.
    """
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    request = google.auth.transport.requests.Request()
    creds.refresh(request)

    card_url = f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/{resource_name}/api{card_path}"
    resp = httpx.get(card_url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
    resp.raise_for_status()

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(resp.json(), f)
        card_file = f.name

    env = {**os.environ, "CLOUDSDK_AUTH_ACCESS_TOKEN": creds.token}
    base = ["gcloud", "alpha", "agent-registry", "services"]
    common = [service_id, f"--location={LOCATION}", f"--project={PROJECT}", "--quiet"]

    exists = subprocess.run(
        [*base, "describe", *common], env=env, capture_output=True
    ).returncode == 0

    if exists:
        cmd = [
            *base, "update", *common,
            "--clear-agent-spec", "--agent-spec-type=a2a-agent-card", f"--agent-spec-content={card_file}",
        ]
    else:
        cmd = [
            *base, "create", *common,
            "--agent-spec-type=a2a-agent-card", f"--agent-spec-content={card_file}",
        ]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    os.unlink(card_file)
    if result.returncode != 0:
        print(f"WARNING: failed to register '{service_id}' in Agent Registry:\n{result.stderr[:1000]}")
    else:
        print(f"Registered in Agent Registry as '{service_id}'.")


PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
REPO = os.environ.get("BYOC_REPO", "trip-planner-agents")
TAG = os.environ.get("BYOC_IMAGE_TAG", "v1")
IMAGE_URI = f"{LOCATION}-docker.pkg.dev/{PROJECT}/{REPO}/sights-researcher-a2a:{TAG}"

vertexai.init(project=PROJECT, location=LOCATION)
client = vertexai.Client(project=PROJECT, location=LOCATION)

config = {
    "display_name": "sights-researcher-a2a",
    "description": (
        "Sights Researcher, deployed as a BYOC A2A service — researches "
        "places to see at a destination, personalised via Memory Bank."
    ),
    "container_spec": {"image_uri": IMAGE_URI},
    "agent_framework": "custom",
    "env_vars": {
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "SESSION_AGENT_ENGINE_ID": os.environ["SESSION_AGENT_ENGINE_ID"],
        "MEMORY_AGENT_ENGINE_ID": os.environ["MEMORY_AGENT_ENGINE_ID"],
    },
}

target = sys.argv[1] if len(sys.argv) > 1 else dotenv_values().get("AGENT_ENGINE_RESOURCE_NAME")  # read fresh from disk, not process env (which Make may have stale-exported)

print(f"Creating/updating Agent Engine from {IMAGE_URI} ...")
if target:
    engine = client.agent_engines.update(name=target, config=config)
else:
    engine = client.agent_engines.create(config=config)
    _set_env_var("AGENT_ENGINE_RESOURCE_NAME", engine.api_resource.name)

print("Deployed:", engine.api_resource.name)
_register_a2a_agent("sights-researcher-a2a", engine.api_resource.name, "/a2a/.well-known/agent-card.json")
