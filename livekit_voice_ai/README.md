# LiveKit Voice AI Agent

A real-time voice assistant that listens through a LiveKit room, understands speech via Deepgram STT, routes queries through a Google ADK agent (backed by Llama 4 on Groq), and responds with Deepgram TTS — all in the browser.

Supports **multiple participants**: anyone in the room can speak and get a response. The agent switches focus to whoever is currently talking.

---

## How It Works

```
Browser mic
    │
    ▼
LiveKit Room (WebRTC)
    │
    ▼
Silero VAD ──► Deepgram STT ──► Google ADK Runner ──► Deepgram TTS ──► LiveKit Room ──► Browser speaker
(detects          (transcribes)     (Llama 4 on Groq)   (synthesizes)
 end of speech)                           │
                                          └──► run_bash("ls", "cat", "grep", ...)
                                                    (reads files in resources/)
```

The agent can read and search files placed in the `resources/` folder. All other bash commands are blocked.

---

## Stack

| Component | Role |
|-----------|------|
| **LiveKit** | WebRTC room for real-time audio |
| **Deepgram** | Speech-to-text (nova-3) and text-to-speech |
| **Silero VAD** | Voice activity detection (local, no cloud) |
| **Google ADK** | Agent framework + tool routing |
| **Groq / Llama 4 Scout** | LLM inference |

---

## Prerequisites

- **Python 3.12** — `brew install python@3.12`
- **Docker** — for the local LiveKit server
- **ffmpeg** — `brew install ffmpeg`

API keys required:

| Service | Purpose | Free Tier |
|---------|---------|-----------|
| [Groq](https://console.groq.com) | LLM inference | Yes |
| [Deepgram](https://deepgram.com) | STT + TTS | Yes — 200 hrs/month |
| [Google AI Studio](https://aistudio.google.com/apikey) | Google ADK | Yes |

---

## Setup

### 1. Enter the directory

```bash
cd livekit_voice_ai
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=your-secret-key-must-be-at-least-32-characters-long-for-security

DEEPGRAM_API_KEY=<your key>
GOOGLE_API_KEY=<your key>
GROQ_API_KEY=<your key>

GOOGLE_GENAI_USE_VERTEXAI=false
```

> The `LIVEKIT_API_SECRET` must match what the Docker server is started with. The Makefile uses a long key — copy it from there if you're unsure.

### 3. Install dependencies

```bash
make install
```

This installs everything into a `.venv` virtual environment. Activate it:

```bash
source .venv/bin/activate
```

---

## Running

You need three terminals:

**Terminal 1 — LiveKit server**
```bash
make livekit-server
```

**Terminal 2 — Agent worker**
```bash
make run
```

The worker prints `Worker registered, waiting for jobs...` when ready.

**Terminal 3 — Web UI**
```bash
make web-ui
```

Open [http://localhost:8001](http://localhost:8001), enter a room name and your name, and click Join.

---

## Using the Agent

Place files in the `resources/` folder. Then ask the agent about them:

- "What files are in the folder?"
- "Read the file named notes.txt"
- "Search for the word 'budget' in the spreadsheet"

The agent uses `ls`, `cat`, `grep`, and similar read-only commands to answer. It cannot modify files or access paths outside `resources/`.

---

## Text-Only Testing (No Microphone Needed)

Test the ADK agent's reasoning in a browser chat UI:

```bash
make playground
```

Open [http://localhost:8000](http://localhost:8000) and type queries. This validates the ADK + Groq + bash tool pipeline without any voice hardware.

---

## Project Structure

```
livekit_voice_ai/
├── agent/
│   ├── __init__.py          # exports root_agent
│   └── agent.py             # ADK agent + safe run_bash tool
├── server/
│   ├── web_ui.py            # FastAPI token server (port 8001)
│   └── index.html           # Browser voice UI (LiveKit JS SDK)
├── livekit_worker.py        # Bridges LiveKit audio pipeline to ADK runner
├── run.py                   # Entry point: python run.py dev
├── resources/               # Files the agent can read (created on first run)
├── requirements.txt         # Dependency list
├── Makefile                 # Dev commands
└── .env.example             # Environment variable template
```

### `livekit_worker.py`

Overrides LiveKit's `llm_node` to route transcribed speech through `Runner.run_async` (Google ADK) instead of calling an LLM directly. Uses `session.room_io.set_participant()` to switch the active speaker when the `active_speakers_changed` room event fires.

### `agent/agent.py`

Defines the ADK agent and the `run_bash` tool. Commands are validated against an allowlist (`ls`, `cat`, `head`, `tail`, `wc`, `file`, `stat`, `grep`, `pwd`, `echo`) and restricted to the `resources/` directory.

### `server/web_ui.py`

FastAPI server that signs LiveKit JWTs and serves `index.html`. No external tools or accounts required to join a room.

---

## Troubleshooting

**`ReadWriteLogRecord` import error on startup**
```bash
.venv/bin/pip install "opentelemetry-sdk==1.39.0" "opentelemetry-api==1.39.0"
```

**Agent does not respond after transcription**
Run `make debug` to see the full log. Check that the ADK runner is processing the transcript (look for `User:` log line in the worker output).

**Deepgram connection closed (net0001)**
Normal when the room is idle — LiveKit reconnects automatically on next speech.

**High memory usage (~900 MB)**
Expected — LiveKit + Deepgram + Silero VAD + Python ADK runtime combined.

**Docker: port 7880 already in use**
```bash
docker ps        # find the container
docker stop <id>
```

**Multiple participants — only one gets responses**
Ensure both participants have their microphones active and that VAD is detecting speech. Check the worker logs for `Speaker switch:` lines.
