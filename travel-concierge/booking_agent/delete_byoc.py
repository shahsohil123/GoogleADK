"""Deletes booking_agent's deployed Agent Engine resource."""

import os
import re
import sys
import warnings

import vertexai

warnings.filterwarnings(
    "ignore", message="The vertexai.Client class is deprecated.*", category=FutureWarning
)
from dotenv import dotenv_values, load_dotenv

load_dotenv(".env", override=True)
if os.path.exists(".env.dev"):
    load_dotenv(".env.dev", override=True)


def _clear_env_var(key: str, path: str = ".env.dev") -> None:
    if not os.path.exists(path):
        return
    existing = open(path).read()
    pattern = re.compile(rf"^{re.escape(key)}=.*\n?", re.MULTILINE)
    with open(path, "w") as f:
        f.write(pattern.sub("", existing))


PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")

target = sys.argv[1] if len(sys.argv) > 1 else (dotenv_values(".env.dev").get("AGENT_ENGINE_RESOURCE_NAME") or dotenv_values(".env").get("AGENT_ENGINE_RESOURCE_NAME"))
if not target:
    print("Nothing to delete: no resource name given and AGENT_ENGINE_RESOURCE_NAME is unset.")
    sys.exit(0)

vertexai.init(project=PROJECT, location=LOCATION)
client = vertexai.Client(project=PROJECT, location=LOCATION)

print(f"Deleting {target} ...")
client.agent_engines.delete(name=target, force=True)
_clear_env_var("AGENT_ENGINE_RESOURCE_NAME")
print("Deleted.")
