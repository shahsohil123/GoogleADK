run:
	source ~/adk-env/bin/activate && \
	export ANTHROPIC_API_KEY=$(shell grep ANTHROPIC_API_KEY ~/.zshrc | tail -1 | cut -d= -f2) && \
	export REPO_PATH=/Users/sohilshah/code && \
	export GOOGLE_GENAI_USE_VERTEXAI=false && \
	cd /Users/sohilshah/code && \
	~/adk-env/bin/adk run git_commit_explainer

web:
	source ~/adk-env/bin/activate && \
	export ANTHROPIC_API_KEY=$(shell grep ANTHROPIC_API_KEY ~/.zshrc | tail -1 | cut -d= -f2) && \
	export REPO_PATH=/Users/sohilshah/code && \
	export GOOGLE_GENAI_USE_VERTEXAI=false && \
	cd /Users/sohilshah/code && \
	~/adk-env/bin/adk web git_commit_explainer
