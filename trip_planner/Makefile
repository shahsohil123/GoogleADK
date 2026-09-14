.PHONY: install create-session-storage create-memory-bank clean

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
