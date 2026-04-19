# Load .env if it exists
ifneq (,$(wildcard .env))
    include .env
    export $(shell sed 's/=.*//' .env)
endif

.PHONY: help install run demo test clean setup-env

setup-env:
	@if [ ! -f .env ]; then \
		echo "Creating .env from .env.example..."; \
		cp .env.example .env; \
		echo "✓ .env created. Edit as needed."; \
	else \
		echo ".env already exists"; \
	fi

help:
	@echo "Mock Booking MCP Server - Available Commands"
	@echo "============================================="
	@echo ""
	@echo "  make setup-env  Create .env from .env.example"
	@echo "  make install    Install dependencies"
	@echo "  make run        Start the MCP server (stdio)"
	@echo "  make demo       Run standalone demo (tests polling + retries)"
	@echo "  make test       Run all tests"
	@echo "  make clean      Remove Python cache and temp files"
	@echo ""
	@echo "Quick Start:"
	@echo "  1. make setup-env"
	@echo "  2. make install"
	@echo "  3. make demo        # See polling in action"
	@echo "  4. make run         # Start server for integration"
	@echo ""
	@echo "Note: .env is automatically loaded when running make commands"
	@echo ""

install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt

run:
	@echo "Starting Mock Booking MCP Server..."
	@echo "Server will listen for MCP protocol on stdio."
	@echo "Use this with ADK agents via McpToolset."
	@echo ""
	python3 server.py

demo:
	@echo "Running standalone demo..."
	@echo "Shows polling pattern with automatic retries."
	@echo "20% of bookings fail to simulate real retry scenarios."
	@echo ""
	python3 demo.py

test:
	@echo "Testing mock booking server..."
	@echo "(Note: Comprehensive tests can be added as test suite grows)"
	python3 -m pytest tests/ -v 2>/dev/null || python3 demo.py

clean:
	@echo "Cleaning up Python cache..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".pytest_cache" -delete
	@echo "Clean!"

.DEFAULT_GOAL := help