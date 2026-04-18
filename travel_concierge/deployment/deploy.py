#!/usr/bin/env python3
"""
Deploy the Travel Concierge to Vertex AI Agent Engine.

Usage:
    python deployment/deploy.py                           # Create new deployment
    python deployment/deploy.py --update                  # Update existing deployment
    python deployment/deploy.py --test                    # Test deployed agent
    python deployment/deploy.py --delete                  # Delete deployment
    python deployment/deploy.py --project my-proj --region us-central1

Prerequisites:
    1. gcloud auth login
    2. gcloud auth application-default login
    3. Enable these APIs in your GCP project:
       - aiplatform.googleapis.com
       - secretmanager.googleapis.com
    4. Set GOOGLE_API_KEY in Secret Manager (or as env var)

Environment variables:
    GOOGLE_CLOUD_PROJECT  — GCP project ID (or pass --project)
    GOOGLE_CLOUD_LOCATION — GCP region (default: us-central1, or pass --region)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEPLOY_METADATA_FILE = Path(__file__).parent / "deployment_metadata.json"
PROJECT_ROOT = Path(__file__).parent.parent


def get_args():
    parser = argparse.ArgumentParser(description="Deploy Travel Concierge to Agent Engine")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                        help="GCP project ID")
    parser.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
                        help="GCP region (default: us-central1)")
    parser.add_argument("--update", action="store_true",
                        help="Update existing deployment instead of creating new")
    parser.add_argument("--test", action="store_true",
                        help="Test the deployed agent")
    parser.add_argument("--delete", action="store_true",
                        help="Delete the deployed agent")
    parser.add_argument("--display-name", default="travel-concierge",
                        help="Display name for the Agent Engine instance")
    return parser.parse_args()


def check_prerequisites(project, region):
    """Verify GCP project and required APIs."""
    if not project:
        print("ERROR: No GCP project specified.")
        print("Set GOOGLE_CLOUD_PROJECT env var or pass --project")
        sys.exit(1)

    print(f"Project:  {project}")
    print(f"Region:   {region}")
    print()

    # Check gcloud auth
    import subprocess
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("ERROR: Not authenticated with gcloud.")
        print("Run: gcloud auth login && gcloud auth application-default login")
        sys.exit(1)

    print("gcloud auth: OK")

    # Check required APIs
    for api in ["aiplatform.googleapis.com"]:
        result = subprocess.run(
            ["gcloud", "services", "list", "--enabled",
             f"--project={project}", f"--filter=name:{api}", "--format=value(name)"],
            capture_output=True, text=True,
        )
        if api not in result.stdout:
            print(f"WARNING: {api} may not be enabled. Enable it with:")
            print(f"  gcloud services enable {api} --project={project}")
        else:
            print(f"API {api}: OK")

    print()


def create_agent_engine(project, region, display_name):
    """Create a new Agent Engine instance with the Travel Concierge."""
    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=project, location=region)

    print("Packaging agent code...")

    # The AdkApp wraps our agent for Agent Engine
    from vertexai.agent_engines.templates.adk import AdkApp

    # Import our agent
    sys.path.insert(0, str(PROJECT_ROOT))
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    os.environ["GOOGLE_CLOUD_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_LOCATION"] = region

    from agent.agent import root_agent

    app = AdkApp(agent=root_agent, enable_tracing=True)

    print(f"Creating Agent Engine instance '{display_name}'...")
    print("This may take 5-10 minutes...")
    print()

    engine = agent_engines.create(
        agent_engine=app,
        display_name=display_name,
        requirements=[
            "google-adk>=1.5.0",
            "mcp>=1.0.0",
        ],
    )

    engine_id = engine.resource_name
    print(f"Agent Engine created: {engine_id}")

    # Save deployment metadata
    metadata = {
        "remote_agent_engine_id": engine_id,
        "deployment_target": "agent_engine",
        "display_name": display_name,
        "project": project,
        "region": region,
        "deployment_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    DEPLOY_METADATA_FILE.write_text(json.dumps(metadata, indent=2))
    print(f"Metadata saved to: {DEPLOY_METADATA_FILE}")

    return engine_id


def update_agent_engine(project, region):
    """Update an existing Agent Engine instance."""
    import vertexai
    from vertexai import agent_engines

    if not DEPLOY_METADATA_FILE.exists():
        print("ERROR: No deployment_metadata.json found. Deploy first with:")
        print("  python deployment/deploy.py")
        sys.exit(1)

    metadata = json.loads(DEPLOY_METADATA_FILE.read_text())
    engine_id = metadata["remote_agent_engine_id"]

    vertexai.init(project=project, location=region)

    print(f"Updating Agent Engine: {engine_id}")

    sys.path.insert(0, str(PROJECT_ROOT))
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    os.environ["GOOGLE_CLOUD_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_LOCATION"] = region

    from agent.agent import root_agent
    from vertexai.agent_engines.templates.adk import AdkApp

    app = AdkApp(agent=root_agent, enable_tracing=True)

    engine = agent_engines.get(engine_id)
    engine.update(
        agent_engine=app,
        requirements=[
            "google-adk>=1.5.0",
            "mcp>=1.0.0",
        ],
    )

    # Update timestamp
    metadata["deployment_timestamp"] = datetime.now(timezone.utc).isoformat()
    DEPLOY_METADATA_FILE.write_text(json.dumps(metadata, indent=2))

    print("Update complete.")
    return engine_id


def test_agent_engine(project, region):
    """Send a test query to the deployed agent."""
    import vertexai

    if not DEPLOY_METADATA_FILE.exists():
        print("ERROR: No deployment_metadata.json found. Deploy first.")
        sys.exit(1)

    metadata = json.loads(DEPLOY_METADATA_FILE.read_text())
    engine_id = metadata["remote_agent_engine_id"]

    vertexai.init(project=project, location=region)

    print(f"Testing Agent Engine: {engine_id}")
    print()

    client = vertexai.Client(location=region)
    agent = client.agent_engines.get(name=engine_id)

    import asyncio

    async def run_test():
        print("Sending: 'Plan a 2-day trip to Kyoto for 2 people, budget $1500'")
        print("-" * 60)
        async for event in agent.async_stream_query(
            message="Plan a 2-day trip to Kyoto for 2 people, budget $1500",
            user_id="test-user",
        ):
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        print(part.text, end="", flush=True)
        print()
        print("-" * 60)
        print("Test complete.")

    asyncio.run(run_test())


def delete_agent_engine(project, region):
    """Delete the deployed Agent Engine instance."""
    import vertexai
    from vertexai import agent_engines

    if not DEPLOY_METADATA_FILE.exists():
        print("ERROR: No deployment_metadata.json found.")
        sys.exit(1)

    metadata = json.loads(DEPLOY_METADATA_FILE.read_text())
    engine_id = metadata["remote_agent_engine_id"]

    vertexai.init(project=project, location=region)

    confirm = input(f"Delete Agent Engine {engine_id}? [y/N] ")
    if confirm.lower() != "y":
        print("Cancelled.")
        return

    print(f"Deleting Agent Engine: {engine_id}")
    engine = agent_engines.get(engine_id)
    engine.delete()

    DEPLOY_METADATA_FILE.unlink()
    print("Deleted successfully.")


def main():
    args = get_args()

    check_prerequisites(args.project, args.region)

    if args.test:
        test_agent_engine(args.project, args.region)
    elif args.delete:
        delete_agent_engine(args.project, args.region)
    elif args.update:
        update_agent_engine(args.project, args.region)
    else:
        create_agent_engine(args.project, args.region, args.display_name)


if __name__ == "__main__":
    main()
