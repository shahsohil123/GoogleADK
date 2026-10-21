UV ?= uv
PYTHON ?= $(UV) run python
ADK ?= $(UV) run adk
PORT ?= 8001

.PHONY: setup install run run-local start eval eval-live adk-eval build-image deploy delete redeploy clean

setup install:
	$(UV) venv --allow-existing --python 3.12 .venv
	$(UV) pip install --python .venv/bin/python -r requirements.txt

run start:
	$(UV) run uvicorn root_concierge_agent.a2a_app:app --host 0.0.0.0 --port $(PORT) --reload

run-local:
	LOCAL_MODE=true OTEL_TO_CLOUD=true $(UV) run uvicorn root_concierge_agent.a2a_app:app --host 0.0.0.0 --port $(PORT) --reload

eval:
	LOCAL_MODE=true OTEL_TO_CLOUD=true $(PYTHON) eval/test_eval.py

eval-live:
	LOCAL_MODE=true OTEL_TO_CLOUD=true RUN_LIVE_ADK_EVAL=true $(PYTHON) eval/test_eval.py

adk-eval:
	LOCAL_MODE=true OTEL_TO_CLOUD=true $(ADK) eval root_concierge_agent \
		eval/data/inspire.test.json \
		eval/data/pretrip.test.json \
		eval/data/intrip.test.json \
		eval/data/planning.test.json \
		eval/data/booking.test.json \
		eval/data/posttrip.test.json \
		eval/data/memory_preferences.test.json \
		--config_file_path=eval/data/test_config.json \
		--print_detailed_results

-include .env
-include .env.dev
export

build-image:
	docker build --platform linux/amd64 -t "$${VERTEX_ENGINE_LOCATION:-us-central1}-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$${BYOC_REPO:-travel-concierge-agents}/root-concierge-agent-a2a:$${BYOC_IMAGE_TAG:-v1}" .
	docker push "$${VERTEX_ENGINE_LOCATION:-us-central1}-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/$${BYOC_REPO:-travel-concierge-agents}/root-concierge-agent-a2a:$${BYOC_IMAGE_TAG:-v1}"

deploy:
	$(PYTHON) deploy_byoc.py

delete:
	$(PYTHON) delete_byoc.py

redeploy: delete build-image deploy

clean:
	rm -rf .venv
	find . -name __pycache__ -type d -exec rm -rf {} +
