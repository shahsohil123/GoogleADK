VENV := /Users/sohilshah/code/GoogleADK/git_commit_explainer/.venv

# Local functionGemma adapter (see functiongemma_server.py).
# Start the server in another shell first:  make server
FG_BASE := http://localhost:11435/v1

server:
	$(VENV)/bin/python /Users/sohilshah/code/GoogleADK/git_commit_explainer/functiongemma_server.py

run:
	source $(VENV)/bin/activate && \
	export OPENAI_API_BASE=$(FG_BASE) && \
	export OPENAI_API_KEY=none && \
	export REPO_PATH=/Users/sohilshah/code && \
	export GOOGLE_GENAI_USE_VERTEXAI=false && \
	cd /Users/sohilshah/code/GoogleADK && \
	$(VENV)/bin/adk run git_commit_explainer

web:
	source $(VENV)/bin/activate && \
	export OPENAI_API_BASE=$(FG_BASE) && \
	export OPENAI_API_KEY=none && \
	export REPO_PATH=/Users/sohilshah/code && \
	export GOOGLE_GENAI_USE_VERTEXAI=false && \
	cd /Users/sohilshah/code/GoogleADK && \
	$(VENV)/bin/adk web git_commit_explainer
