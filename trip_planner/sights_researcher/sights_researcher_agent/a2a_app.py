"""A2A wrapping for `root_agent`. Run locally with
`uvicorn sights_researcher_agent.a2a_app:app` (`make start`), or deployed to
Agent Engine as a BYOC container by `deploy_byoc.py`.
"""

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a

from sights_researcher_agent.agent import root_agent
from sights_researcher_agent.card import AGENT_CARD, RPC_PATH
from sights_researcher_agent.runner import create_runner

app = to_a2a(
    root_agent,
    runner=create_runner,
    agent_card=AGENT_CARD,
    rpc_path=RPC_PATH,
    port=int(os.environ.get("PORT", "8003")),
)
