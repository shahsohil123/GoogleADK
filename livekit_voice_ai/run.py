#!/usr/bin/env python3
"""
Entry point for the Livekit Voice AI agent.

Usage
─────
  python run.py dev          # run Livekit voice worker (requires Livekit installed)
  adk web .                  # text-based testing via browser UI (recommended first)
  adk run .                  # text-based testing via CLI

Environment variables (set in .env):
  LIVEKIT_URL          wss://your-livekit-host  (or ws://localhost:7880 for dev)
  LIVEKIT_API_KEY      your Livekit API key
  LIVEKIT_API_SECRET   your Livekit API secret
  DEEPGRAM_API_KEY     your Deepgram API key
  GOOGLE_API_KEY       your Gemini API key (for ADK agent)
  WORKSPACE            directory the bash agent operates in (default: ~)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── opentelemetry compatibility patch ────────────────────────────────────────
# Livekit tries to import ReadWriteLogRecord from opentelemetry.sdk._logs
# which was moved in opentelemetry-sdk 1.39+. Patch it back if missing.
try:
    import opentelemetry.sdk._logs as _otel_logs
    # Try to get ReadWriteLogRecord from the right place
    if not hasattr(_otel_logs, 'ReadWriteLogRecord'):
        found = False
        # Try multiple locations where it might be
        for module_path in [
            'opentelemetry.sdk._logs._internal',
            'opentelemetry.sdk._logs.log_record_processor',
        ]:
            try:
                mod = __import__(module_path, fromlist=['ReadWriteLogRecord'])
                if hasattr(mod, 'ReadWriteLogRecord'):
                    _otel_logs.ReadWriteLogRecord = mod.ReadWriteLogRecord
                    found = True
                    break
            except (ImportError, AttributeError):
                continue

        # If still not found, create a minimal stub
        if not found:
            class ReadWriteLogRecord:
                pass
            _otel_logs.ReadWriteLogRecord = ReadWriteLogRecord
except ImportError:
    pass  # opentelemetry not installed

# Check if Livekit is available before trying to import the worker
try:
    import livekit  # noqa: F401
except ImportError:
    print("\n" + "═" * 60)
    print("  ⚠️  Livekit is not installed.")
    print("═" * 60)
    print("\nLivekit has a known dependency conflict with opentelemetry.")
    print("You can still test the ADK agent without voice:\n")
    print("  Text test (browser UI):")
    print("    adk web .\n")
    print("  Text test (CLI):")
    print("    adk run .\n")
    print("To install Livekit (may have conflicts):")
    print("  uv pip install livekit-agents livekit-plugins-deepgram livekit-plugins-silero\n")
    sys.exit(1)

from livekit_worker import server  # noqa: F401
from livekit.agents import cli

if __name__ == "__main__":
    cli.run_app(server)
