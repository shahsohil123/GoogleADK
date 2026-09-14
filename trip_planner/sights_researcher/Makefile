.PHONY: install playground start build-image deploy clean

install:
	python3.12 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt

# ADK's dev UI, talking to the agent directly (bypasses A2A and Memory Bank —
# uses ADK's own in-memory session/memory services).
playground:
	.venv/bin/adk web .

# Start the A2A service on :8003, wired to Vertex AI Agent Engine Session
# Service + Memory Bank. Needs SESSION_AGENT_ENGINE_ID/MEMORY_AGENT_ENGINE_ID
# in .env — see ../create_session_storage.py and ../create_memory_bank.py
# (shared across every agent in this repo).
start:
	.venv/bin/uvicorn sights_researcher_agent.a2a_app:app --host 0.0.0.0 --port 8003

# Builds and pushes the BYOC container image (the same a2a_app.py the local
# A2A service runs) to the shared Artifact Registry repo.
build-image:
	gcloud builds submit --tag "$${GOOGLE_CLOUD_LOCATION:-us-central1}-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/trip-planner-agents/sights-researcher-a2a:v1" .

# Deploys the built image to Vertex AI Agent Engine as a real A2A service.
# Run build-image first.
deploy:
	.venv/bin/python deploy_byoc.py

clean:
	rm -rf .venv
	find . -name __pycache__ -type d -exec rm -rf {} +
