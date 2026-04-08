#!/usr/bin/env python3
"""
FastAPI server that issues LiveKit room tokens and serves the browser UI.

Usage:
    make web-ui           (uses venv Python)
    python server/web_ui.py

Then open http://localhost:8001
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from livekit.api import AccessToken, VideoGrants

load_dotenv()

LIVEKIT_URL = os.environ["LIVEKIT_URL"]
LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]

app = FastAPI(title="LiveKit Voice AI")


class TokenRequest(BaseModel):
    room: str
    username: str


class TokenResponse(BaseModel):
    token: str
    url: str


@app.post("/api/token", response_model=TokenResponse)
async def get_token(req: TokenRequest):
    try:
        token = (
            AccessToken(api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
            .with_identity(req.username)
            .with_grants(VideoGrants(room_join=True, room=req.room, agent=True))
            .to_jwt()
        )
        ws_url = LIVEKIT_URL if not LIVEKIT_URL.startswith("http") else "ws" + LIVEKIT_URL[4:]
        return TokenResponse(token=token, url=ws_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def index():
    ui_path = Path(__file__).parent / "index.html"
    if not ui_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(ui_path, media_type="text/html")


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    print(f"Web UI: http://localhost:8001  |  LiveKit: {LIVEKIT_URL}")
    uvicorn.run(app, host="127.0.0.1", port=8001)
