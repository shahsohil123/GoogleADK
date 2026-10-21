"""Build, deployment, and verification orchestrator for the 16 Travel Concierge BYOC A2A agents.

Provides:
  - Verification of Artifact Registry images, Vertex AI Agent Engine resources,
    and Google Cloud Agent Registry A2A services across all 16 agents.
  - Smart `build-images-all` that skips already-pushed images (unless FORCE_BUILD=true),
    tracks per-agent build failures, and prints a post-build verification summary.
  - Smart `deploy-all` that verifies image existence before deploying, tracks
    succeeded vs. errored agents, and prints a full post-deploy verification table.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path
from typing import Dict, List, Set, Tuple

from dotenv import dotenv_values, load_dotenv

warnings.filterwarnings(
    "ignore", message="The vertexai.Client class is deprecated.*", category=FutureWarning
)

ROOT_DIR = Path(__file__).resolve().parent

# Load root .env and .env.dev
load_dotenv(ROOT_DIR / ".env", override=True)
if (ROOT_DIR / ".env.dev").exists():
    load_dotenv(ROOT_DIR / ".env.dev", override=True)

AGENTS: List[Tuple[str, str, str]] = [
    ("place_agent", "place-agent-a2a", "ADK"),
    ("poi_agent", "poi-agent-a2a", "ADK"),
    ("flight_search_agent", "flight-search-agent-a2a", "ADK"),
    ("flight_seat_selection_agent", "flight-seat-selection-agent-a2a", "ADK"),
    ("hotel_search_agent", "hotel-search-agent-a2a", "ADK"),
    ("hotel_room_selection_agent", "hotel-room-selection-agent-a2a", "ADK"),
    ("itinerary_agent", "itinerary-agent-a2a", "ADK"),
    ("day_of_agent", "day-of-agent-a2a", "ADK"),
    ("trip_monitor_agent", "trip-monitor-agent-a2a", "ADK"),
    ("inspiration_agent", "inspiration-agent-a2a", "ADK"),
    ("planning_agent", "planning-agent-a2a", "ADK"),
    ("booking_agent", "booking-agent-a2a", "LangGraph"),
    ("pre_trip_agent", "pre-trip-agent-a2a", "CrewAI"),
    ("in_trip_agent", "in-trip-agent-a2a", "ADK"),
    ("post_trip_agent", "post-trip-agent-a2a", "ADK"),
    ("root_agent", "root-concierge-agent-a2a", "ADK"),
]

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.environ.get("VERTEX_ENGINE_LOCATION", "us-central1")
REPO = os.environ.get("BYOC_REPO", "travel-concierge-agents")
TAG = os.environ.get("BYOC_IMAGE_TAG", "v1")


def get_pushed_images() -> Set[str]:
    """Return the set of image names (e.g., 'place-agent-a2a') present in Artifact Registry."""
    repo_Prefix = f"{LOCATION}-docker.pkg.dev/{PROJECT}/{REPO}"
    cmd = [
        "gcloud",
        "artifacts",
        "docker",
        "images",
        "list",
        repo_Prefix,
        f"--project={PROJECT}",
        "--format=value(package)",
        "--quiet",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return set()
    names: Set[str] = set()
    for line in res.stdout.splitlines():
        line = line.strip()
        if line:
            names.add(line.rsplit("/", 1)[-1])
    return names


def get_live_reasoning_engines() -> Dict[str, str]:
    """Return map of full ReasoningEngine resource_name -> display_name in Vertex AI."""
    try:
        import vertexai

        vertexai.init(project=PROJECT, location=LOCATION)
        client = vertexai.Client(project=PROJECT, location=LOCATION)
        live: Dict[str, str] = {}
        for engine in client.agent_engines.list():
            res_name = getattr(engine.api_resource, "name", "")
            disp_name = getattr(engine.api_resource, "display_name", "")
            if res_name:
                live[res_name] = disp_name
        return live
    except Exception:
        return {}


def get_registered_agent_services() -> Set[str]:
    """Return set of service IDs registered in Google Cloud Agent Registry."""
    cmd = [
        "gcloud",
        "alpha",
        "agent-registry",
        "services",
        "list",
        f"--location={LOCATION}",
        f"--project={PROJECT}",
        "--format=value(name)",
        "--quiet",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return set()
    services: Set[str] = set()
    for line in res.stdout.splitlines():
        line = line.strip()
        if line:
            services.add(line.rsplit("/", 1)[-1])
    return services


def get_configured_engine_name(agent_dir: str) -> str:
    """Read AGENT_ENGINE_RESOURCE_NAME from <agent_dir>/.env.dev or <agent_dir>/.env."""
    dev_path = ROOT_DIR / agent_dir / ".env.dev"
    env_path = ROOT_DIR / agent_dir / ".env"
    if dev_path.exists():
        val = dotenv_values(dev_path).get("AGENT_ENGINE_RESOURCE_NAME")
        if val:
            return val
    if env_path.exists():
        val = dotenv_values(env_path).get("AGENT_ENGINE_RESOURCE_NAME")
        if val:
            return val
    return ""


def print_verification_report(
    build_errors: Dict[str, str] | None = None,
    deploy_errors: Dict[str, str] | None = None,
) -> Tuple[int, int]:
    """Print a comprehensive status table of all 16 agents and return (images_ready, deployed_ready)."""
    pushed_images = get_pushed_images()
    live_engines = get_live_reasoning_engines()
    registered_services = get_registered_agent_services()

    print("\n" + "=" * 118)
    print(
        f" TRAVEL CONCIERGE — CLOUD AGENT RUNTIME VERIFICATION REPORT (Project: {PROJECT}, Location: {LOCATION})"
    )
    print("=" * 118)
    header = (
        f"{'AGENT DIR':<29} {'FRAMEWORK':<10} {'ARTIFACT REG IMAGE':<20} "
        f"{'AGENT ENGINE ID':<22} {'AGENT REGISTRY':<18} {'OVERALL STATUS'}"
    )
    print(header)
    print("-" * 118)

    images_ready = 0
    deployed_ready = 0
    missing_images: List[str] = []
    failed_deploys: List[str] = []

    for agent_dir, service_id, framework in AGENTS:
        has_image = service_id in pushed_images
        if has_image:
            images_ready += 1
            img_status = f"OK ({TAG})"
        else:
            img_status = "MISSING"
            missing_images.append(agent_dir)

        configured_engine = get_configured_engine_name(agent_dir)
        # Also match by display_name if .env.dev wasn't updated yet
        matched_engine = configured_engine if configured_engine in live_engines else ""
        if not matched_engine:
            for r_name, d_name in live_engines.items():
                if d_name == service_id:
                    matched_engine = r_name
                    break

        engine_short = matched_engine.rsplit("/", 1)[-1] if matched_engine else "NOT DEPLOYED"
        in_registry = service_id in registered_services
        reg_status = "REGISTERED" if in_registry else "NOT REGISTERED"

        if build_errors and agent_dir in build_errors:
            overall = f"BUILD ERROR ({build_errors[agent_dir]})"
        elif deploy_errors and agent_dir in deploy_errors:
            overall = f"DEPLOY ERROR ({deploy_errors[agent_dir]})"
            failed_deploys.append(agent_dir)
        elif has_image and matched_engine and in_registry:
            overall = "DEPLOYED & REGISTERED"
            deployed_ready += 1
        elif has_image and matched_engine:
            overall = "ENGINE LIVE (Unregistered)"
        elif has_image:
            overall = "IMAGE READY (Pending Deploy)"
            failed_deploys.append(agent_dir)
        else:
            overall = "PENDING IMAGE BUILD"
            failed_deploys.append(agent_dir)

        print(
            f"{agent_dir:<29} {framework:<10} {img_status:<20} "
            f"{engine_short:<22} {reg_status:<18} {overall}"
        )

    print("-" * 118)
    print(
        f" SUMMARY: {images_ready}/16 Container Images in Artifact Registry | "
        f"{deployed_ready}/16 Agents Deployed & Registered in Agent Runtime"
    )
    print("=" * 118)

    if missing_images:
        print(f"\n[!] Missing / Failed Images ({len(missing_images)}): {', '.join(missing_images)}")
        print("    Retry building missing images with: make build-images-all")
    if deploy_errors:
        print(f"\n[!] Errored Deployments ({len(deploy_errors)}): {', '.join(deploy_errors.keys())}")
        for ag, err in deploy_errors.items():
            print(f"    - {ag}: {err}")
        print("    Retry deploying pending/failed agents with: make deploy-all")
    print()
    return images_ready, deployed_ready


def _run_make_target(
    idx: int,
    total: int,
    agent_dir: str,
    service_id: str,
    target: str,
    print_lock: threading.Lock,
    stagger_sec: float = 0.0,
) -> Tuple[str, int, float, str]:
    """Run `make -C <agent_dir> <target>` in a worker thread with prefixed real-time output."""
    if stagger_sec > 0:
        time.sleep(stagger_sec)
    t0 = time.monotonic()
    with print_lock:
        print(f"[{idx}/{total}] [START] {agent_dir} ({service_id}) -> make {target}", flush=True)

    proc = subprocess.Popen(
        ["make", "-C", str(ROOT_DIR / agent_dir), f"PYTHON={sys.executable}", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    last_lines: List[str] = []
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip("\n")
        if line:
            last_lines.append(line)
            if len(last_lines) > 10:
                last_lines.pop(0)
            with print_lock:
                print(f"  [{agent_dir}] {line}", flush=True)

    rc = proc.wait()
    elapsed = time.monotonic() - t0
    with print_lock:
        status_str = "DONE" if rc == 0 else f"FAILED (exit {rc})"
        print(
            f"[{idx}/{total}] [{status_str}] {agent_dir} ({service_id}) in {elapsed:.1f}s",
            flush=True,
        )
    err_summary = f"exit code {rc}"
    if rc != 0 and last_lines:
        err_summary = f"exit {rc}: {last_lines[-1][:80]}"
    return agent_dir, rc, elapsed, err_summary


def _sync_root_env_dev() -> None:
    """Sync root_agent/.env.dev AGENT_ENGINE_RESOURCE_NAME to root .env.dev if updated."""
    root_agent_env = ROOT_DIR / "root_agent" / ".env.dev"
    top_env = ROOT_DIR / ".env.dev"
    if not root_agent_env.exists() or not top_env.exists():
        return
    new_engine = dotenv_values(root_agent_env).get("AGENT_ENGINE_RESOURCE_NAME")
    if not new_engine:
        return
    content = top_env.read_text()
    pattern = re.compile(r"^AGENT_ENGINE_RESOURCE_NAME=.*$", re.MULTILINE)
    if pattern.search(content):
        updated = pattern.sub(f"AGENT_ENGINE_RESOURCE_NAME={new_engine}", content)
        if updated != content:
            top_env.write_text(updated)


def run_build_all(force: bool = False, max_workers: int = 16) -> int:
    """Build container images for all 16 agents in parallel and push to Artifact Registry."""
    subprocess.run(
        ["gcloud", "auth", "configure-docker", f"{LOCATION}-docker.pkg.dev", "--quiet"],
        check=False,
    )
    pushed_images = set() if force else get_pushed_images()
    build_errors: Dict[str, str] = {}
    to_build: List[Tuple[int, str, str]] = []

    for idx, (agent_dir, service_id, _) in enumerate(AGENTS, start=1):
        if not force and service_id in pushed_images:
            print(f"[{idx}/16] Skipping {agent_dir} ({service_id}:{TAG} already in Artifact Registry)")
            continue
        to_build.append((idx, agent_dir, service_id))

    if to_build:
        workers = min(max_workers, len(to_build))
        print(f"\n=== Building {len(to_build)} agent image(s) in parallel (workers={workers}) ===\n")
        print_lock = threading.Lock()
        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_run_make_target, idx, 16, agent_dir, service_id, "build-image", print_lock)
                for idx, agent_dir, service_id in to_build
            ]
            for fut in concurrent.futures.as_completed(futures):
                agent_dir, rc, _, err_summary = fut.result()
                if rc != 0:
                    build_errors[agent_dir] = err_summary
        print(f"\n=== Parallel image build finished in {time.monotonic() - t0:.1f}s ===")

    images_ready, _ = print_verification_report(build_errors=build_errors)
    return 0 if (not build_errors and images_ready == len(AGENTS)) else 1


def run_deploy_all(force_update: bool = False, max_workers: int = 16) -> int:
    """Deploy all 16 BYOC agents to Vertex AI Agent Engine in parallel and verify status."""
    pushed_images = get_pushed_images()
    live_engines = get_live_reasoning_engines()
    registered_services = get_registered_agent_services()
    deploy_errors: Dict[str, str] = {}
    to_deploy: List[Tuple[int, str, str]] = []

    for idx, (agent_dir, service_id, _) in enumerate(AGENTS, start=1):
        if service_id not in pushed_images:
            msg = f"Image {service_id}:{TAG} missing in Artifact Registry"
            print(f"[{idx}/16] [SKIP/ERROR] {agent_dir}: {msg}")
            deploy_errors[agent_dir] = msg
            continue

        configured_engine = get_configured_engine_name(agent_dir)
        already_live = configured_engine in live_engines or any(
            d == service_id for d in live_engines.values()
        )
        already_registered = service_id in registered_services

        if not force_update and already_live and already_registered:
            print(
                f"[{idx}/16] Skipping {agent_dir} ({service_id} already deployed & registered in Agent Runtime)"
            )
            continue

        to_deploy.append((idx, agent_dir, service_id))

    if to_deploy:
        workers = min(max_workers, len(to_deploy))
        print(
            f"\n=== Deploying {len(to_deploy)} agent(s) to Vertex AI Agent Engine in parallel (workers={workers}) ===\n"
        )
        print_lock = threading.Lock()
        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    _run_make_target,
                    idx,
                    16,
                    agent_dir,
                    service_id,
                    "deploy",
                    print_lock,
                    (w_idx % workers) * 1.5,
                )
                for w_idx, (idx, agent_dir, service_id) in enumerate(to_deploy)
            ]
            for fut in concurrent.futures.as_completed(futures):
                agent_dir, rc, _, err_summary = fut.result()
                if rc != 0:
                    deploy_errors[agent_dir] = err_summary
        _sync_root_env_dev()
        print(f"\n=== Parallel deployment finished in {time.monotonic() - t0:.1f}s ===")

    _, deployed_ready = print_verification_report(deploy_errors=deploy_errors)
    return 0 if (not deploy_errors and deployed_ready == len(AGENTS)) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Build, deploy, and verify Travel Concierge BYOC agents.")
    parser.add_argument("--verify", action="store_true", help="Print status report of all 16 agents.")
    parser.add_argument("--build-all", action="store_true", help="Build missing (or all) agent images in parallel.")
    parser.add_argument("--force-build", action="store_true", help="Rebuild all images even if present.")
    parser.add_argument("--deploy-all", action="store_true", help="Deploy pending (or all) agents in parallel and verify.")
    parser.add_argument("--force-deploy", action="store_true", help="Redeploy/update all agents in parallel even if live.")
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=int(os.environ.get("JOBS", "8")),
        help="Maximum number of parallel workers (default: 8).",
    )
    args = parser.parse_args()

    if args.build_all:
        sys.exit(run_build_all(force=args.force_build, max_workers=max(1, args.jobs)))
    elif args.deploy_all:
        sys.exit(run_deploy_all(force_update=args.force_deploy, max_workers=max(1, args.jobs)))
    else:
        print_verification_report()


if __name__ == "__main__":
    main()

