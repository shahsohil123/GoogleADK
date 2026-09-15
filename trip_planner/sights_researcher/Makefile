.PHONY: install playground start build-image deploy delete redeploy clean

# Makes .env's vars (GOOGLE_CLOUD_PROJECT, etc.) available to every recipe
# below as both Make variables and shell environment variables — without
# this, `$$GOOGLE_CLOUD_PROJECT` in build-image is empty unless the caller
# happened to export it manually first, producing a malformed image tag
# (a real failure this hit in practice, not a hypothetical).
-include .env
export

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

# Deletes the deployed Agent Engine resource (from AGENT_ENGINE_RESOURCE_NAME
# in .env). Irreversible.
delete:
	.venv/bin/python delete_byoc.py

# Fresh delete + rebuild + redeploy, e.g. to clear a broken deployment
# before a demo. Prefer `make deploy` alone for a normal update in place.
redeploy: delete build-image deploy

clean:
	rm -rf .venv
	find . -name __pycache__ -type d -exec rm -rf {} +
