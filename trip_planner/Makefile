.PHONY: install create-session-storage create-memory-bank redeploy-all clean

install:
	python3.12 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt

# One-time: creates the shared Agent Engine resources ADK agents in this
# repo persist state to. Paste the printed ID into each agent's own .env.
create-session-storage:
	.venv/bin/python create_agent_engine.py session

create-memory-bank:
	.venv/bin/python create_agent_engine.py memory

clean:
	rm -rf .venv
	find . -maxdepth 1 -name __pycache__ -type d -exec rm -rf {} +

# Deletes and fully redeploys all three agents from scratch — e.g. to reset
# to a clean state before a demo. Each agent's own venv must already exist
# (run `make install` inside each agent directory first). The shared
# Session Service and Memory Bank resources are untouched by this — only
# the three BYOC Agent Engine resources are deleted and recreated.
redeploy-all:
	$(MAKE) -C trip_planning redeploy
	$(MAKE) -C sights_researcher redeploy
	$(MAKE) -C paypal_payments redeploy
