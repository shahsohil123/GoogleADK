"""
LiveKit multi-participant agent with turn-taking.

Routes voice transcripts through Google ADK, responds via TTS.
Switches active speaker on VAD-detected activity.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable

from dotenv import load_dotenv

# opentelemetry compatibility shim (livekit-agents 1.5.1 expects this)
try:
    from opentelemetry.sdk._logs import ReadWriteLogRecord  # noqa: F401
except ImportError:
    try:
        import opentelemetry.sdk._logs as _otel_logs
        from opentelemetry.sdk._logs._internal import ReadWriteLogRecord
        _otel_logs.ReadWriteLogRecord = ReadWriteLogRecord
    except ImportError:
        pass

from livekit.agents import (
    Agent as LivekitAgent,
    AgentSession,
    AgentServer,
    JobContext,
    JobProcess,
    cli,
    room_io,
)
from livekit.agents import llm as lk_llm
from livekit.agents.llm import ChatContext
from livekit.plugins import deepgram, silero
from livekit import rtc

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import root_agent

load_dotenv()
logger = logging.getLogger("livekit-voice-ai")

# Suppress noisy framework loggers
logging.getLogger("livekit.agents.inference.interruption").setLevel(logging.CRITICAL)
logging.getLogger("livekit.agents.inference").setLevel(logging.CRITICAL)


class _StubLLM(lk_llm.LLM):
    """Satisfies the framework's isinstance(llm, LLM) guard so llm_node is invoked."""
    def chat(self, **kwargs):
        raise RuntimeError("_StubLLM.chat should never be called")


class VoiceAgent(LivekitAgent):
    """Routes transcribed speech through Google ADK and streams the response."""

    def __init__(self, runner: Runner, session_service: InMemorySessionService) -> None:
        super().__init__(
            instructions="You are a helpful voice assistant.",
            llm=_StubLLM(),
        )
        self._runner = runner
        self._session_service = session_service
        self._adk_session_id: str | None = None

    async def on_enter(self) -> None:
        session = await self._session_service.create_session(
            app_name="voice_ai", user_id="voice_user"
        )
        self._adk_session_id = session.id
        logger.info(f"ADK session created: {self._adk_session_id}")

    def llm_node(self, chat_ctx, tools, model_settings):
        return self._adk_generate(chat_ctx)

    async def _adk_generate(self, chat_ctx: ChatContext) -> AsyncIterable[str]:
        user_text = ""
        for msg in reversed(list(chat_ctx.messages())):
            if msg.role == "user" and getattr(msg, "text_content", None):
                user_text = msg.text_content.strip()
                break

        if not user_text:
            yield "I didn't catch that."
            return

        logger.info(f"User: {user_text}")

        try:
            parts: list[str] = []
            async for event in self._runner.run_async(
                user_id="voice_user",
                session_id=self._adk_session_id,
                new_message=types.Content(
                    role="user", parts=[types.Part(text=user_text)]
                ),
            ):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            parts.append(part.text)

            response = "".join(parts).strip()
            logger.info(f"Agent: {response[:120] if response else '(empty)'}")
            yield response or "I have no response for that."

        except Exception:
            logger.exception("ADK error")
            yield "Sorry, something went wrong."


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer()
server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"Room: {ctx.room.name}")

    session_service = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name="voice_ai", session_service=session_service)
    agent = VoiceAgent(runner, session_service)

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        tts=deepgram.TTS(),
        vad=ctx.proc.userdata["vad"],
        turn_handling={"interruption": {"mode": "vad"}},
    )

    current_speaker: str | None = None

    def on_active_speakers_changed(speakers: list[rtc.Participant]) -> None:
        nonlocal current_speaker
        remote = [s for s in speakers if s.identity in ctx.room.remote_participants]
        if not remote:
            return
        new_speaker = remote[0].identity
        if new_speaker != current_speaker:
            logger.info(f"Speaker switch: {current_speaker} -> {new_speaker}")
            current_speaker = new_speaker
            try:
                session.room_io.set_participant(new_speaker)
            except RuntimeError:
                logger.warning("Speaker switch: room_io not ready yet")

    def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        nonlocal current_speaker
        logger.info(f"Participant connected: {participant.identity}")
        if current_speaker is None:
            current_speaker = participant.identity
            try:
                session.room_io.set_participant(current_speaker)
            except RuntimeError:
                pass

    # Register before session.start() to catch all participant events
    ctx.room.on("active_speakers_changed", on_active_speakers_changed)
    ctx.room.on("participant_connected", on_participant_connected)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(auto_gain_control=True),
            close_on_disconnect=False,
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)
