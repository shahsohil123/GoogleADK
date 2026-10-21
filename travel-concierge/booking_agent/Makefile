UV ?= uv
PYTHON ?= $(UV) run python

.PHONY: setup install start studio studio-safari build-image deploy delete redeploy clean

-include .env
-include .env.dev
export

setup install:
	$(UV) venv --allow-existing --python 3.12 .venv
	$(UV) pip install --python .venv/bin/python -r requirements.txt

# Start the LangGraph booking_agent as an A2A service on :8004.
start:
	$(UV) run uvicorn booking_langgraph_agent.agent:app --host 0.0.0.0 --port 8004

# Launch LangGraph Studio (dev UI) against the graph directly, bypassing A2A.
studio:
	$(UV) run langgraph dev

studio-safari:
	$(UV) run langgraph dev --tunnel

build-image:
	docker build --platform linux/amd64 -t "$${VERTEX_ENGINE_LOCATION:-us-central1}-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$${BYOC_REPO:-travel-concierge-agents}/booking-agent-a2a:$${BYOC_IMAGE_TAG:-v1}" .
	docker push "$${VERTEX_ENGINE_LOCATION:-us-central1}-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$${BYOC_REPO:-travel-concierge-agents}/booking-agent-a2a:$${BYOC_IMAGE_TAG:-v1}"

deploy:
	$(PYTHON) deploy_byoc.py

delete:
	$(PYTHON) delete_byoc.py

redeploy: delete build-image deploy

clean:
	rm -rf .venv
	find . -name __pycache__ -type d -exec rm -rf {} +
