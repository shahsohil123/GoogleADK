UV ?= uv
PYTHON ?= $(UV) run python

.PHONY: setup install start build-image deploy delete redeploy clean

-include .env
-include .env.dev
export

setup install:
	$(UV) venv --allow-existing --python 3.12 .venv
	$(UV) pip install --python .venv/bin/python -r requirements.txt

# Start flight-search-agent-a2a locally on :8010
start:
	$(UV) run uvicorn flight_search_concierge_agent.a2a_app:app --host 0.0.0.0 --port 8010

build-image:
	docker build --platform linux/amd64 -t "$${VERTEX_ENGINE_LOCATION:-us-central1}-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$${BYOC_REPO:-travel-concierge-agents}/flight-search-agent-a2a:$${BYOC_IMAGE_TAG:-v1}" .
	docker push "$${VERTEX_ENGINE_LOCATION:-us-central1}-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$${BYOC_REPO:-travel-concierge-agents}/flight-search-agent-a2a:$${BYOC_IMAGE_TAG:-v1}"

deploy:
	$(PYTHON) deploy_byoc.py

delete:
	$(PYTHON) delete_byoc.py

redeploy: delete build-image deploy

clean:
	rm -rf .venv
	find . -name __pycache__ -type d -exec rm -rf {} +
