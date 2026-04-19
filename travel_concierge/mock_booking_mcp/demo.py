#!/usr/bin/env python3
"""
Demo: How the travel_concierge agent would use the mock booking MCP.

Shows the polling pattern:
1. submit_booking() → get job_id
2. Loop: check_booking_status(job_id) until completed/failed
3. Retry on failure
"""

import asyncio
import json
import time

# Simulate the MCP tool responses
# In real usage, these would come from the MCP server

jobs = {}


async def submit_booking(flight_id: str, passengers: int) -> dict:
    """Simulate MCP tool: submit_booking"""
    import uuid
    import random
    from datetime import datetime

    job_id = f"BK-{uuid.uuid4().hex[:8].upper()}"
    jobs[job_id] = {
        "status": "pending",
        "created_at": datetime.now(),
        "flight_id": flight_id,
        "passengers": passengers,
        "should_fail": random.random() < 0.2,  # 20% fail rate
    }
    return {
        "job_id": job_id,
        "status": "pending",
        "flight_id": flight_id,
        "passengers": passengers,
    }


async def check_booking_status(job_id: str) -> dict:
    """Simulate MCP tool: check_booking_status"""
    from datetime import datetime

    if job_id not in jobs:
        return {"job_id": job_id, "status": "error", "error": "Job not found"}

    job = jobs[job_id]
    elapsed = (datetime.now() - job["created_at"]).total_seconds()
    processing_time = 5 if not job["should_fail"] else 4

    if elapsed < 1:
        job["status"] = "pending"
        progress = 0
    elif elapsed < processing_time:
        job["status"] = "processing"
        progress = int((elapsed / processing_time) * 100)
    else:
        if job["should_fail"]:
            job["status"] = "failed"
            return {
                "job_id": job_id,
                "status": "failed",
                "error": "Booking processing failed",
            }
        else:
            job["status"] = "completed"
            return {
                "job_id": job_id,
                "status": "completed",
                "confirmation_number": f"CONF-{job_id}",
                "total_price": f"${500 + (job['passengers'] * 150)}.00",
            }

    return {
        "job_id": job_id,
        "status": "processing",
        "progress": progress,
    }


async def agent_booking_flow(flight_id: str, passengers: int, max_retries: int = 3):
    """
    Simulates how the travel_concierge agent would handle booking.

    Pattern:
    1. Call submit_booking → get job_id
    2. Poll check_booking_status until completion or failure
    3. Retry on failure (up to max_retries)
    """
    print(f"\n🎫 Starting booking for {passengers} passengers on {flight_id}")

    for attempt in range(max_retries):
        print(f"\n   Attempt {attempt + 1}/{max_retries}")

        # Step 1: Submit booking
        submit_result = await submit_booking(flight_id, passengers)
        job_id = submit_result["job_id"]
        print(f"   ✓ Submitted booking. Job ID: {job_id}")

        # Step 2: Poll until complete
        poll_count = 0
        while True:
            poll_count += 1
            await asyncio.sleep(0.5)  # Wait 500ms between polls (in real usage: 1-3s)

            status_result = await check_booking_status(job_id)

            if status_result["status"] == "processing":
                progress = status_result.get("progress", 0)
                print(f"   ⏳ Processing... {progress}% (poll #{poll_count})")

            elif status_result["status"] == "completed":
                print(f"   ✅ Booking confirmed!")
                print(f"      Confirmation: {status_result['confirmation_number']}")
                print(f"      Price: {status_result['total_price']}")
                return status_result  # Success!

            elif status_result["status"] == "failed":
                print(f"   ❌ Booking failed: {status_result['error']}")
                break  # Retry

            else:
                print(f"   ⚠️  Unexpected status: {status_result['status']}")
                break

        if attempt < max_retries - 1:
            print(f"   🔄 Retrying in 1 second...")
            await asyncio.sleep(1)

    print(f"\n   ❌ Booking failed after {max_retries} attempts")
    return None


async def main():
    """Run demo with multiple scenarios."""
    print("=" * 60)
    print("MOCK BOOKING MCP SERVER DEMO")
    print("=" * 60)

    # Scenario 1: Successful booking
    print("\n[Scenario 1: Successful booking on first attempt]")
    result = await agent_booking_flow("FL-2024-NYC-LAX", passengers=2, max_retries=3)

    # Scenario 2: Successful booking (may have retries due to random failures)
    print("\n[Scenario 2: Another booking (may fail and retry)]")
    result = await agent_booking_flow("FL-2024-SFO-NYC", passengers=1, max_retries=3)

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())