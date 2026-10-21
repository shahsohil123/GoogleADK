UV ?= uv
PYTHON ?= $(UV) run python
ADK ?= $(UV) run adk

AGENTS = \
	place_agent \
	poi_agent \
	flight_search_agent \
	flight_seat_selection_agent \
	hotel_search_agent \
	hotel_room_selection_agent \
	itinerary_agent \
	day_of_agent \
	trip_monitor_agent \
	inspiration_agent \
	planning_agent \
	booking_agent \
	pre_trip_agent \
	in_trip_agent \
	post_trip_agent \
	root_agent

.PHONY: setup install create-shared-engines setup-bigquery docker-up docker-down docker-restart docker-redeploy run-local run-local-a2a run-cloud ui ui-local ui-dev eval eval-live adk-eval build-images-all deploy-all verify-deployment delete-all clean $(AGENTS)

setup install:
	$(UV) venv --allow-existing --python 3.12 .venv
	$(UV) pip install --python .venv/bin/python -r requirements.txt

create-shared-engines:
	$(PYTHON) create_agent_engine.py session
	$(PYTHON) create_agent_engine.py memory

setup-bigquery:
	$(PYTHON) setup_bigquery_looker.py

docker-up:
	docker build -t travel-concierge-local:latest -f Dockerfile.local .
	docker compose up -d --force-recreate

docker-down:
	docker compose down -v --remove-orphans

docker-restart docker-redeploy:
	docker compose down -v --remove-orphans
	docker build -t travel-concierge-local:latest -f Dockerfile.local .
	docker compose up -d --force-recreate

TRAVELER ?= sohil

run-local:
	PYTHONWARNINGS=ignore LOCAL_MODE=true OTEL_TO_CLOUD=false BQ_ANALYTICS_ENABLED=false $(PYTHON) run_local.py --traveler "$(TRAVELER)"

run-local-a2a:
	PYTHONWARNINGS=ignore LOCAL_MODE=true OTEL_TO_CLOUD=false BQ_ANALYTICS_ENABLED=false $(PYTHON) run_local.py --start-all-a2a --traveler "$(TRAVELER)"

run-cloud:
	set -a && . ./.env.dev && set +a && PYTHONWARNINGS=ignore LOCAL_MODE=false OTEL_TO_CLOUD=true BQ_ANALYTICS_ENABLED=true $(PYTHON) run_local.py --traveler "$(TRAVELER)"

ui:
	PYTHONWARNINGS=ignore $(PYTHON) aura_voyage_ui.py --port 8090 --traveler "$(TRAVELER)"

ui-local:
	PYTHONWARNINGS=ignore $(PYTHON) aura_voyage_ui.py --port 8090 --env local --traveler "$(TRAVELER)"

ui-dev:
	PYTHONWARNINGS=ignore $(PYTHON) aura_voyage_ui.py --port 8090 --env dev --traveler "$(TRAVELER)"

eval:
	PYTHONWARNINGS=ignore LOCAL_MODE=true OTEL_TO_CLOUD=false BQ_ANALYTICS_ENABLED=false $(PYTHON) root_agent/eval/test_eval.py

eval-live:
	PYTHONWARNINGS=ignore LOCAL_MODE=true OTEL_TO_CLOUD=false BQ_ANALYTICS_ENABLED=false RUN_LIVE_ADK_EVAL=true $(PYTHON) root_agent/eval/test_eval.py

adk-eval:
	PYTHONWARNINGS=ignore LOCAL_MODE=true $(ADK) eval root_agent/root_concierge_agent \
		root_agent/eval/data/inspire.test.json \
		root_agent/eval/data/pretrip.test.json \
		root_agent/eval/data/intrip.test.json \
		root_agent/eval/data/planning.test.json \
		root_agent/eval/data/booking.test.json \
		root_agent/eval/data/posttrip.test.json \
		root_agent/eval/data/memory_preferences.test.json \
		--config_file_path=root_agent/eval/data/test_config.json \
		--print_detailed_results

JOBS ?= 8

build-images-all:
	$(PYTHON) verify_deployment.py --build-all --jobs $(JOBS) $(if $(filter true 1,$(SKIP_EXISTING)),,--force-build)

deploy-all:
	$(PYTHON) verify_deployment.py --deploy-all --jobs $(JOBS) $(if $(filter true 1,$(FORCE_DEPLOY)),--force-deploy,)

verify-deployment:
	$(PYTHON) verify_deployment.py --verify

delete-all:
	@for agent in $(AGENTS); do \
		(echo "=== Deleting $$agent ===" && $(MAKE) -C $$agent delete || true) & \
	done; wait

clean:
	rm -rf .venv
	find . -name __pycache__ -type d -exec rm -rf {} +
