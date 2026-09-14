.PHONY: install start studio studio-safari build-image deploy clean

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -r requirements.txt

# Start the LangGraph PayPal payments agent as an A2A service on :8002.
start:
	.venv/bin/uvicorn paypal_agent.agent:app --host 0.0.0.0 --port 8002

# Launch LangGraph Studio (dev UI) against the graph directly, bypassing A2A.
# Use this in Chrome/Firefox. Note the UI page itself is hosted at
# smith.langchain.com — only the API server is local.
studio:
	.venv/bin/langgraph dev

# Same, but tunneled — only needed if your browser is Safari (it blocks
# Studio's page from reaching plain http://localhost). Each run gets a new
# random *.trycloudflare.com URL, which Studio may ask you to allow-list.
studio-safari:
	.venv/bin/langgraph dev --tunnel

# Builds and pushes the BYOC container image (the same agent.py the local
# A2A service runs) to the shared Artifact Registry repo.
build-image:
	gcloud builds submit --tag "$${GOOGLE_CLOUD_LOCATION:-us-central1}-docker.pkg.dev/$$GOOGLE_CLOUD_PROJECT/trip-planner-agents/paypal-payments-a2a:v1" .

# Deploys the built image to Vertex AI Agent Engine as a real A2A service.
# Run build-image first.
deploy:
	.venv/bin/python deploy_byoc.py

clean:
	rm -rf .venv
	find . -name __pycache__ -type d -exec rm -rf {} +
