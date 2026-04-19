#!/usr/bin/env python3
"""
Mock Booking MCP Server

Simulates a flight booking system with async job processing.
- submit_booking: POST request, returns job_id
- check_booking_status: Query job status (pending → processing → completed/failed)

Jobs take 4-5 seconds to process. 20% fail randomly to test retry logic.

The ReflectAndRetryToolPlugin (from ADK) will handle:
- Detecting failures
- LLM reflection on what went wrong
- Intelligent retry strategies
"""

import asyncio
import json
import random
import uuid
from datetime import datetime

import mcp.server.stdio
from mcp.server import Server
from mcp.types import Tool, TextContent


# In-memory job store: job_id -> {status, created_at, flight_id, passengers, failure_count}
jobs = {}


async def submit_booking(flight_id: str, passengers: int) -> dict:
    """
    Submit a flight booking request.

    Args:
        flight_id: The flight identifier (e.g., "FL-2024-001")
        passengers: Number of passengers

    Returns:
        {"job_id": "...", "status": "pending", "message": "Booking submitted"}
    """
    job_id = f"BK-{uuid.uuid4().hex[:8].upper()}"

    jobs[job_id] = {
        "status": "pending",
        "created_at": datetime.now(),
        "flight_id": flight_id,
        "passengers": passengers,
        "failure_count": 0,
        "should_fail": random.random() < 0.2,  # 20% failure rate for testing
    }

    return {
        "job_id": job_id,
        "status": "pending",
        "flight_id": flight_id,
        "passengers": passengers,
        "message": f"Booking submitted. Job ID: {job_id}. Processing in 4-5 seconds.",
    }


async def check_booking_status(job_id: str) -> dict:
    """
    Check the status of a booking job.

    Args:
        job_id: The job ID returned from submit_booking

    Returns:
        {
            "job_id": "...",
            "status": "pending|processing|completed|failed",
            "progress": 0-100 (for processing),
            "confirmation_number": "..." (if completed),
            "error": "..." (if failed)
        }
    """
    if job_id not in jobs:
        return {
            "job_id": job_id,
            "status": "error",
            "error": f"Job {job_id} not found",
        }

    job = jobs[job_id]
    elapsed = (datetime.now() - job["created_at"]).total_seconds()

    # Processing takes 4-5 seconds
    processing_time = 5 if not job["should_fail"] else 4

    if elapsed < 1:
        # First second: pending
        job["status"] = "pending"
        progress = 0
    elif elapsed < processing_time:
        # Middle: processing
        job["status"] = "processing"
        progress = int((elapsed / processing_time) * 100)
    else:
        # Done processing: check if should fail
        if job["should_fail"]:
            job["status"] = "failed"
            job["failure_count"] += 1
            return {
                "job_id": job_id,
                "status": "failed",
                "error": "Booking processing failed. Temporary system error. Please retry.",
                "retry_attempt": job["failure_count"],
            }
        else:
            job["status"] = "completed"
            confirmation_number = f"CONF-{job_id[:8]}-{datetime.now().strftime('%Y%m%d')}"
            return {
                "job_id": job_id,
                "status": "completed",
                "confirmation_number": confirmation_number,
                "flight_id": job["flight_id"],
                "passengers": job["passengers"],
                "total_price": f"${500 + (job['passengers'] * 150)}.00",
                "booking_reference": confirmation_number,
            }

    return {
        "job_id": job_id,
        "status": "processing",
        "progress": progress,
    }


server = Server("mock-booking-mcp")


@server.list_tools()
async def list_tools():
    """List available tools."""
    return [
        Tool(
            name="submit_booking",
            description="Submit a flight booking request. Returns job_id to poll for completion.",
            inputSchema={
                "type": "object",
                "properties": {
                    "flight_id": {
                        "type": "string",
                        "description": "Flight identifier (e.g., 'FL-2024-001')",
                    },
                    "passengers": {
                        "type": "integer",
                        "description": "Number of passengers",
                    },
                },
                "required": ["flight_id", "passengers"],
            },
        ),
        Tool(
            name="check_booking_status",
            description="Check booking status. Poll this until status is 'completed' or 'failed'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID from submit_booking",
                    },
                },
                "required": ["job_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    if name == "submit_booking":
        result = await submit_booking(
            arguments["flight_id"],
            arguments["passengers"],
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "check_booking_status":
        result = await check_booking_status(arguments["job_id"])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, asyncio.Event())


if __name__ == "__main__":
    asyncio.run(main())