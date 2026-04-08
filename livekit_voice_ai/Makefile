SHELL := /bin/bash
VENV  := .venv
PYTHON := $(VENV)/bin/python
UV    := uv

.PHONY: install playground run help token livekit-server debug quick-test web-ui

help:
	@echo ""
	@echo "  Livekit Voice AI Agent — Available Commands"
	@echo "  ─────────────────────────────────────────────"
	@echo "  make install          Install all dependencies"
	@echo "  make playground       Launch ADK web UI (text-based testing)"
	@echo "  make run              Start Livekit voice agent worker"
	@echo "  make debug            Start agent with verbose logging"
	@echo "  make web-ui           Start web UI server (browser voice interface)"
	@echo "  make token            Generate a room join token"
	@echo "  make livekit-server   Start local Livekit server (Docker)"
	@echo "  make quick-test       Show livekit-cli join command with token"
	@echo ""

install:
	python3.12 -m venv $(VENV)
	@echo "Step 0: Installing system tools..."
	@command -v ffmpeg >/dev/null || (echo "Installing ffmpeg via brew..." && brew install ffmpeg)
	@echo "Step 1: Installing build tools..."
	$(PYTHON) -m pip install --upgrade pip setuptools wheel
	@echo "Step 2: Installing dependencies..."
	$(PYTHON) -m pip install "google-adk[extensions]" google-genai google-cloud-aiplatform pydantic litellm
	@echo "Step 3: Installing ADK tools..."
	$(PYTHON) -m pip install fastapi uvicorn watchdog click pyyaml flit_core
	@echo "Step 4: Installing utilities..."
	$(PYTHON) -m pip install python-dotenv requests mcp authlib
	@echo "Step 5: Installing Livekit voice stack..."
	$(PYTHON) -m pip install --no-deps livekit-agents==1.5.1
	$(PYTHON) -m pip install livekit-plugins-deepgram livekit-plugins-silero
	@echo "Step 6: Installing ML libraries (may take 10-15 min)..."
	$(PYTHON) -m pip install transformers torch
	@echo "Step 7: Installing Livekit and ML dependencies..."
	$(PYTHON) -m pip install numpy protobuf aiohttp websockets av scipy soundfile accelerate
	@echo ""
	@echo "✅ Installation complete!"
	@echo ""
	@echo "Activate with:"
	@echo "  source $(VENV)/bin/activate"
	@echo ""
	@echo "Then test:"
	@echo "  make test             # Verify setup"
	@echo "  make playground       # Text-based testing (recommended first)"
	@echo ""
	@echo "For voice support:"
	@echo "  make livekit-server   # Terminal 1: Start Livekit server"
	@echo "  make run              # Terminal 2: Start voice agent"

playground:
	@# adk web . from THIS directory — ADK finds agent/ subfolder as the agent package
	GOOGLE_GENAI_USE_VERTEXAI=false $(VENV)/bin/adk web .

run:
	$(PYTHON) run.py dev

web-ui:
	$(PYTHON) server/web_ui.py

token:
	@$(PYTHON) -c "\
from dotenv import load_dotenv; import os; load_dotenv(); \
from livekit import api; \
tok = api.AccessToken(os.environ['LIVEKIT_API_KEY'], os.environ['LIVEKIT_API_SECRET']) \
    .with_grants(api.VideoGrants(room_join=True, room='voice-room', agent=True)) \
    .with_identity('user') \
    .to_jwt(); \
print('\n  Room token (paste into agents-playground.livekit.io):\n'); \
print(' ', tok, '\n')"

debug:
	LIVEKIT_LOG_LEVEL=debug $(PYTHON) run.py dev

livekit-server:
	docker run --rm \
		-p 7880:7880 -p 7881:7881 -p 7882:7882/udp \
		-e LIVEKIT_KEYS="devkey: your-secret-key-must-be-at-least-32-characters-long-for-security" \
		-e LIVEKIT_RTC_PORT_RANGE_START=7882 \
		-e LIVEKIT_RTC_PORT_RANGE_NUM=100 \
		livekit/livekit-server

quick-test:
	@echo ""
	@echo "🔑 Generating token with agent dispatch enabled..."
	@echo ""
	@$(PYTHON) -c "\
from dotenv import load_dotenv; import os; load_dotenv(); \
from livekit import api; \
tok = api.AccessToken(os.environ['LIVEKIT_API_KEY'], os.environ['LIVEKIT_API_SECRET']) \
    .with_grants(api.VideoGrants(room_join=True, room='voice-room', agent=True)) \
    .with_identity('test-user') \
    .to_jwt(); \
print('📋 Use this command to join the room:\n'); \
print('  lk join-room \\\\'); \
print('    --url ws://localhost:7880 \\\\'); \
print('    --room voice-room \\\\'); \
print('    --api-key devkey \\\\'); \
print('    --api-secret secret \\\\'); \
print('    --identity test-user\n'); \
print('✅ Make sure these are running first:'); \
print('   Terminal 1: make livekit-server'); \
print('   Terminal 2: make debug'); \
print('')"

