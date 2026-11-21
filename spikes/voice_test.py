"""Throwaway voice worker for the phase 0 tests. Not product code.

Start it and leave it running:      python spikes/voice_test.py dev
Then start a test with:             python spikes/start_test.py <mode> [phone]

Modes, chosen by the dispatch metadata:
  sarvam    Sarvam speech-to-text and text-to-speech around an OpenAI model (phone)
  realtime  OpenAI's speech-to-speech model (phone)
  avatar    Sarvam pipeline with a Synthesia avatar (browser)

The prompt below is a fixed test script on purpose: the test compares speech
quality, so both modes must be asked to hold the same conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from livekit import api, rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli, room_io
from livekit.plugins import openai, sarvam, silero

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
OUT = ROOT / "spikes" / "out"
OUT.mkdir(parents=True, exist_ok=True)

AGENT_NAME = "agenthire-spike"
TIME_CAP_SECONDS = 150
log = logging.getLogger("spike")

LANGUAGE_NAMES = {"te": "Telugu", "hi": "Hindi", "en": "English"}
LANGUAGE_CODES = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}

TEST_INSTRUCTIONS = """You are a voice assistant on a test call. Speak only {language}, in short natural sentences,
the way people speak on the phone. Keep English words that people normally use, such as "visiting charge".

First say that you are an AI assistant making a test call and that the call is recorded. Then ask these three
things, one at a time, waiting for each answer: what kind of work the person does, what time they are free
tomorrow, and how much they charge for a visit. Repeat back each answer briefly so they know you understood.
If something is unclear, ask them to repeat it. After the third answer, thank them and say goodbye."""


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=prewarm)


class Recorder:
    """Writes the transcript and timing of one test call as JSON lines."""

    def __init__(self, room: str, mode: str):
        self.path = OUT / f"{room}.jsonl"
        self.start = time.time()
        self.write("start", mode=mode)

    def write(self, kind: str, **fields: Any) -> None:
        entry = {"t": round(time.time() - self.start, 2), "kind": kind, **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def turn_handling(on_phone: bool) -> dict[str, Any]:
    """The phone settings that worked in SevaMitra (docs/TECH_STACK.md, section 2)."""
    try:
        from livekit.agents import inference
        detection: Any = inference.TurnDetector()
    except Exception as exc:
        log.warning("Turn detector unavailable, using voice detection only: %s", exc)
        detection = "vad"
    handling: dict[str, Any] = {
        "turn_detection": detection,
        "interruption": {"mode": "vad", "min_words": 2, "discard_audio_if_uninterruptible": False,
                         "min_duration": 0.8 if on_phone else 0.5},
    }
    if on_phone:
        handling["endpointing"] = {"min_delay": 0.8, "max_delay": 3.5}
    return handling


def build_session(mode: str, language: str, vad: Any, on_phone: bool) -> AgentSession:
    if mode == "realtime":
        return AgentSession(llm=openai.realtime.RealtimeModel(model=os.getenv("REALTIME_MODEL", "gpt-realtime-2.1")))
    code = LANGUAGE_CODES[language]
    return AgentSession(
        stt=sarvam.STT(language=code, model="saaras:v4", mode="codemix"),
        llm=openai.LLM(model=os.environ["LLM_MODEL_FAST"], reasoning_effort="none"),
        tts=sarvam.TTS(target_language_code=code, model="bulbul:v3", speaker=os.getenv("TTS_SPEAKER", "shubh")),
        vad=vad,
        turn_handling=turn_handling(on_phone),
    )


def noise_cancellation(on_phone: bool) -> Any:
    try:
        from livekit.plugins import noise_cancellation as nc
        return nc.BVCTelephony() if on_phone else nc.BVC()
    except Exception as exc:
        log.warning("Noise cancellation unavailable: %s", exc)
        return None


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    mode, language, phone = meta.get("mode", "sarvam"), meta.get("language", "te"), meta.get("phone")
    recorder = Recorder(ctx.room.name, mode)
    log.info("Test %s in %s, room %s, phone %s", mode, language, ctx.room.name, bool(phone))
    await ctx.connect()

    if phone:
        allowed = [n.strip() for n in os.getenv("ALLOWED_NUMBERS", "").split(",") if n.strip()]
        if phone not in allowed:
            raise RuntimeError("Refusing to dial a number that is not in ALLOWED_NUMBERS")
        dial_started = time.time()
        await ctx.api.sip.create_sip_participant(api.CreateSIPParticipantRequest(
            sip_trunk_id=os.environ["LIVEKIT_SIP_OUTBOUND_TRUNK_ID"], sip_call_to=phone, room_name=ctx.room.name,
            participant_identity="phone", participant_name="Test phone", wait_until_answered=True, play_dialtone=False))
        recorder.write("answered", seconds_to_answer=round(time.time() - dial_started, 1))
        await asyncio.sleep(1.0)  # let the person get the phone to their ear

    participant = await ctx.wait_for_participant()
    on_phone = participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
    session = build_session(mode, language, ctx.proc.userdata["vad"], on_phone)

    @session.on("conversation_item_added")
    def _item(ev: Any) -> None:
        item = ev.item
        text = getattr(item, "text_content", None)
        if text:
            recorder.write("said", role=getattr(item, "role", "?"), text=text,
                           interrupted=bool(getattr(item, "interrupted", False)))

    @session.on("metrics_collected")
    def _metrics(ev: Any) -> None:
        m = ev.metrics
        fields = {name: round(getattr(m, name), 3) for name in
                  ("end_of_utterance_delay", "transcription_delay", "ttft", "ttfb", "duration", "audio_duration")
                  if isinstance(getattr(m, name, None), (int, float))}
        recorder.write("metric", type=type(m).__name__, **fields)

    @session.on("close")
    def _closed(ev: Any) -> None:
        recorder.write("closed", reason=str(getattr(getattr(ev, "reason", ""), "value", getattr(ev, "reason", ""))))

    output_audio = True
    if mode == "avatar":
        from livekit.plugins import synthesia
        avatar = synthesia.AvatarSession(
            synthesia.AvatarConfig(avatar_ids=[meta["avatar_id"]]), api_key=os.environ["AVATAR_API_KEY"])
        started = time.time()
        await avatar.start(session, room=ctx.room)
        recorder.write("avatar_started", seconds=round(time.time() - started, 1))
        output_audio = False  # the avatar publishes the agent's audio together with its video

    await session.start(
        agent=Agent(instructions=TEST_INSTRUCTIONS.format(language=LANGUAGE_NAMES[language])),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(noise_cancellation=noise_cancellation(on_phone)),
            audio_output=output_audio, close_on_disconnect=True),
    )
    await session.generate_reply(instructions="Begin the call now with your opening sentence.")

    async def enforce_time_cap() -> None:
        await asyncio.sleep(TIME_CAP_SECONDS)
        recorder.write("time_cap")
        await ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))

    cap = asyncio.create_task(enforce_time_cap())
    ctx.add_shutdown_callback(lambda: _cancel(cap))


async def _cancel(task: asyncio.Task) -> None:
    task.cancel()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 1:
        sys.argv.append("dev")
    cli.run_app(server)
