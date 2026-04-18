.PHONY: install start-researcher run-shopper clean

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -r requirements.txt

# Terminal 1: start the LangGraph product researcher as an A2A service.
start-researcher:
	.venv/bin/uvicorn langgraph_researcher.product_researcher:app --host 0.0.0.0 --port 8001

# Terminal 2: launch the ADK dev UI; pick `personal_shopper` in the dropdown.
run-shopper:
	.venv/bin/adk web adk_shopper

clean:
	rm -rf .venv
	find . -name __pycache__ -type d -exec rm -rf {} +