"""Deletes the PayPal payments agent's deployed Agent Engine resource.

    python delete_byoc.py                  # deletes AGENT_ENGINE_RESOURCE_NAME from .env
    python delete_byoc.py <resource_name>   # deletes an explicit resource instead

Clears AGENT_ENGINE_RESOURCE_NAME from .env afterward, so a following
`deploy_byoc.py` (no argument) creates a fresh resource rather than trying
to update one that no longer exists.
"""

import os
import re
import sys

import warnings

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


def _clear_env_var(key: str, path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    existing = open(path).read()
    pattern = re.compile(rf"^{re.escape(key)}=.*\n?", re.MULTILINE)
    with open(path, "w") as f:
        f.write(pattern.sub("", existing))


PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

target = sys.argv[1] if len(sys.argv) > 1 else dotenv_values().get("AGENT_ENGINE_RESOURCE_NAME")  # read fresh from disk, not process env (which Make may have stale-exported)
if not target:
    # Nothing deployed yet (e.g. first run, or a prior delete already ran) —
    # this is a no-op, not an error, so `make redeploy` stays idempotent and
    # falls through to deploy_byoc.py creating a fresh resource.
    print("Nothing to delete: no resource name given and AGENT_ENGINE_RESOURCE_NAME is unset.")
    sys.exit(0)

vertexai.init(project=PROJECT, location=LOCATION)
client = vertexai.Client(project=PROJECT, location=LOCATION)

print(f"Deleting {target} ...")
client.agent_engines.delete(name=target, force=True)
_clear_env_var("AGENT_ENGINE_RESOURCE_NAME")
print("Deleted.")
