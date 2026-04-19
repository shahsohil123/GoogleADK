# LiveKit Voice AI Agent

> A real-time voice assistant that listens in a LiveKit room, transcribes
> with Deepgram, routes through a **[Google ADK](https://adk.dev)** agent
> (Llama 4 on Groq), and responds with TTS — all in the browser, with
> support for multiple participants.

![framework](https://img.shields.io/badge/framework-Google%20ADK-4285F4) ![transport](https://img.shields.io/badge/transport-LiveKit-FF4500) ![model](https://img.shields.io/badge/model-Llama%204%20on%20Groq-34A853)

---

## What this demonstrates

- **Voice as a first-class ADK surface.** The Google ADK `Runner` is
  wired into LiveKit's audio pipeline by overriding `llm_node`, so the
  agent's tool-calling and session state work over a real WebRTC room
  instead of a chat UI.
- **Multi-participant speaker switching.** Anyone in the room can
  speak. The worker listens to the `active_speakers_changed` event and
  re-targets the ADK session at whoever is currently talking.
- **Sandboxed shell tooling over voice.** A constrained `run_bash` tool
  lets the agent read files in `resources/` (via `ls`, `cat`, `grep`,
  etc.) while blocking anything outside the folder or on an allowlist —
  all triggered by plain speech.

---

## The scenario

> *"What files are in the folder?"* → *"Read the file named notes.txt"*
> → *"Search for the word 'budget' in the spreadsheet"*

1. You drop files into `resources/` and join a LiveKit room in your
   browser.
2. You speak. Silero VAD detects end of speech; Deepgram transcribes.
3. The transcript goes through the ADK `Runner` — the agent reasons,
   calls `run_bash` if it needs to look at a file, and produces a reply.
4. Deepgram TTS synthesises the reply; LiveKit streams it back to the
   browser speaker.

---

## Architecture

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

The agent can read and search files placed in the `resources/` folder.
All other bash commands are blocked at the tool layer.

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

| Service | Purpose | Free tier |
|---------|---------|-----------|
| [Groq](https://console.groq.com) | LLM inference | Yes |
| [Deepgram](https://deepgram.com) | STT + TTS | Yes — 200 hrs/month |
| [Google AI Studio](https://aistudio.google.com/apikey) | Google ADK | Yes |

---

## Setup

```bash
cd livekit_voice_ai
cp .env.example .env          # fill in the keys below
make install                  # creates .venv and installs deps
```

`.env` minimum:

```dotenv
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=your-secret-key-must-be-at-least-32-characters-long-for-security

DEEPGRAM_API_KEY=<your key>
GOOGLE_API_KEY=<your key>
GROQ_API_KEY=<your key>

GOOGLE_GENAI_USE_VERTEXAI=false
```

> The `LIVEKIT_API_SECRET` must match what the Docker server is started
> with. The Makefile uses a long key — copy it from there if unsure.

---

## Running it

You need three terminals.

### Option 1 — Full voice stack

**Terminal 1 — LiveKit server**
```bash
make livekit-server
```

**Terminal 2 — Agent worker**
```bash
make run
```

Worker prints `Worker registered, waiting for jobs...` when ready.

**Terminal 3 — Web UI**
```bash
make web-ui
```

Open <http://localhost:8001>, enter a room name and your name, and
click Join. Place files into `resources/` and ask about them by voice.

### Option 2 — Text-only (no microphone)

```bash
make playground
```

Open <http://localhost:8000> and type queries. This validates the ADK +
Groq + bash tool pipeline without any voice hardware.

---

## Project structure

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
├── Makefile                 # Dev commands
├── .env.example
├── requirements.txt
└── README.md
```

---

## Key patterns

### 1. Routing LiveKit audio through the ADK Runner

`livekit_worker.py` overrides LiveKit's `llm_node` to push transcribed
speech through `Runner.run_async` (Google ADK) instead of calling an
LLM directly. Session state, tool calls, and events flow through ADK
exactly as they would in a chat agent.

### 2. Multi-participant speaker switching

```python
@ctx.room.on("active_speakers_changed")
def _on_speakers_changed(speakers):
    if speakers:
        session.room_io.set_participant(speakers[0].identity)
```

The worker re-targets the ADK session at whoever is currently talking
so everyone in the room gets responses — not just the first joiner.

### 3. Sandboxed shell tool

```python
ALLOW = {"ls", "cat", "head", "tail", "wc", "file",
         "stat", "grep", "pwd", "echo"}

def run_bash(cmd: str) -> str:
    binary = cmd.strip().split()[0]
    if binary not in ALLOW:
        return f"Command {binary} not allowed"
    # also restricts paths to resources/ ...
```

Commands are validated against an allowlist and restricted to the
`resources/` directory. No writes, no network calls.

---

## Troubleshooting

**`ReadWriteLogRecord` import error on startup**
```bash
.venv/bin/pip install "opentelemetry-sdk==1.39.0" "opentelemetry-api==1.39.0"
```

**Agent does not respond after transcription**
Run `make debug` to see the full log. Check that the ADK runner is
processing the transcript (look for `User:` log line in worker output).

**Deepgram connection closed (net0001)**
Normal when the room is idle — LiveKit reconnects on next speech.

**High memory usage (~900 MB)**
Expected — LiveKit + Deepgram + Silero VAD + Python ADK runtime
combined.

**Docker: port 7880 already in use**
```bash
docker ps        # find the container
docker stop <id>
```

**Multiple participants — only one gets responses**
Ensure both participants have their microphones active and that VAD
is detecting speech. Check worker logs for `Speaker switch:` lines.

---

## Next steps

- **Swap the `run_bash` tool for a real knowledge base** — point it at
  a vector store or a document MCP server so the agent can answer
  questions about your docs, not just a `resources/` folder.
- **Add a wake-word** so the agent only speaks when addressed
  (*"hey concierge…"*), useful for multi-person rooms where side
  conversation shouldn't trigger responses.
- **Deploy the worker to Cloud Run** and point a hosted LiveKit Cloud
  project at it — the whole voice stack becomes a single public URL.
- **Move the ADK agent into a subagent graph** so a router can decide
  between a shell tool agent, a calendar agent, a search agent, etc.,
  all reachable from the same voice interface.
