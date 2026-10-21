"""Deploys the LangGraph booking_agent to Vertex AI Agent Engine as a
Bring-Your-Own-Container (BYOC) A2A service and registers its AgentCard in
Google Cloud Agent Registry. Wired to the shared Vertex AI Session Service
and Memory Bank.
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

warnings.filterwarnings(
    "ignore", message="The vertexai.Client class is deprecated.*", category=FutureWarning
)
from dotenv import dotenv_values, load_dotenv

load_dotenv(".env", override=True)
if os.path.exists(".env.dev"):
    load_dotenv(".env.dev", override=True)


def _set_env_var(key: str, value: str, path: str = ".env.dev") -> None:
    line = f"{key}={value}\n"
    existing = open(path).read() if os.path.exists(path) else ""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    updated = pattern.sub(line.rstrip("\n"), existing) if pattern.search(existing) else existing + line
    with open(path, "w") as f:
        f.write(updated)


def _register_a2a_agent(service_id: str, resource_name: str, card_path: str) -> None:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    request = google.auth.transport.requests.Request()
    creds.refresh(request)

    card_url = f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/{resource_name}/api{card_path}"
    resp = httpx.get(card_url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
    resp.raise_for_status()

    card_text = resp.text.replace("global-aiplatform.googleapis.com", f"{LOCATION}-aiplatform.googleapis.com").replace("/locations/global/", f"/locations/{LOCATION}/")
    card_obj = json.loads(card_text)
    if isinstance(card_obj.get("capabilities"), dict):
        card_obj["capabilities"]["streaming"] = False
        card_obj["capabilities"]["pushNotifications"] = False
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(card_obj, f)
        card_file = f.name

    env = {**os.environ, "CLOUDSDK_AUTH_ACCESS_TOKEN": creds.token}
    base = ["gcloud", "alpha", "agent-registry", "services"]
    for reg_loc in dict.fromkeys([LOCATION, "global"]):
        common = [service_id, f"--location={reg_loc}", f"--project={PROJECT}", "--quiet"]
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
        if result.returncode != 0:
            print(f"WARNING: failed to register '{service_id}' in Agent Registry ({reg_loc}):\n{result.stderr[:1000]}")
        else:
            print(f"Registered in Agent Registry ({reg_loc}) as '{service_id}'.")
    os.unlink(card_file)


PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
REPO = os.environ.get("BYOC_REPO", "travel-concierge-agents")
TAG = os.environ.get("BYOC_IMAGE_TAG", "v1")
IMAGE_URI = f"{LOCATION}-docker.pkg.dev/{PROJECT}/{REPO}/booking-agent-a2a:{TAG}"

vertexai.init(project=PROJECT, location=LOCATION)
client = vertexai.Client(project=PROJECT, location=LOCATION)

config = {
    "display_name": "booking-agent-a2a",
    "description": (
        "Booking agent (LangGraph), deployed as a BYOC A2A service — "
        "creates reservations for flights, hotels, and activities, presents "
        "payment choices, and processes payments."
    ),
    "container_spec": {"image_uri": IMAGE_URI},
    "agent_framework": "custom",
    "env_vars": {
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "GOOGLE_CLOUD_LOCATION": "global",
        "VERTEX_ENGINE_LOCATION": LOCATION,
        "GENAI_MODEL": os.environ.get("GENAI_MODEL", "gemini-3-flash-preview"),
        "LOCAL_MODE": "false",
        "OTEL_TO_CLOUD": "true",
        "BQ_ANALYTICS_ENABLED": "true",
        "SESSION_AGENT_ENGINE_ID": os.environ["SESSION_AGENT_ENGINE_ID"],
        "MEMORY_AGENT_ENGINE_ID": os.environ["MEMORY_AGENT_ENGINE_ID"],
    },
}

def _resolve_existing_engine(display_name: str) -> str | None:
    explicit = sys.argv[1] if len(sys.argv) > 1 else (
        dotenv_values(".env.dev").get("AGENT_ENGINE_RESOURCE_NAME")
        or dotenv_values(".env").get("AGENT_ENGINE_RESOURCE_NAME")
    )
    live_by_name = {}
    live_by_display = {}
    for eng in client.agent_engines.list():
        rname = getattr(eng.api_resource, "name", "")
        dname = getattr(eng.api_resource, "display_name", "")
        if rname:
            live_by_name[rname] = dname
        if dname and dname not in live_by_display:
            live_by_display[dname] = rname
    if explicit and explicit in live_by_name:
        return explicit
    return live_by_display.get(display_name)


target = _resolve_existing_engine(config["display_name"])

import random, time as _time
for _attempt in range(5):
    try:
        if target:
            print(f"Updating existing Agent Engine {target} from {IMAGE_URI} (attempt {_attempt + 1}) ...", flush=True)
            engine = client.agent_engines.update(name=target, config=config)
        else:
            print(f"Creating new Agent Engine from {IMAGE_URI} (attempt {_attempt + 1}) ...", flush=True)
            engine = client.agent_engines.create(config=config)
        _set_env_var("AGENT_ENGINE_RESOURCE_NAME", engine.api_resource.name)
        break
    except Exception as _exc:
        if ("429" in str(_exc) or "RESOURCE_EXHAUSTED" in str(_exc)) and _attempt < 4:
            _wait = 22.0 + (_attempt * 15.0) + random.uniform(1.0, 8.0)
            print(f"Hit Reasoning Engine write quota (429), retrying in {_wait:.1f}s ...", flush=True)
            _time.sleep(_wait)
            continue
        raise

print("Deployed:", engine.api_resource.name)
_register_a2a_agent("booking-agent-a2a", engine.api_resource.name, "/.well-known/agent-card.json")
