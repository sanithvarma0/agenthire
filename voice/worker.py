"""The LiveKit voice worker: one job per conversation (docs/LLD.md, section 9).

LiveKit handles listening and speaking (Sarvam speech-to-text and text-to-speech,
voice detection, turn-taking). Every turn runs through the same `TextConversation`
the evals test, so what passes in text mode is what runs on a call: the same
instructions, status note, tools, one reply per turn and cleaned output.

The back end creates the conversation and dispatches this worker with
`{"conversation_id": ..., "job_id": ...}` as job metadata. The worker fetches the
record, reports every event back, and never dials anyone (layer rule).

    .venv\\Scripts\\python -m voice.worker dev
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from livekit import api, rtc
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, StopResponse, cli, room_io
from livekit.agents.llm import ChatContext, ChatMessage
# Every plugin is imported here, at module load: LiveKit registers plugins only on the main
# thread, and importing one inside a job fails ("Plugins must be registered on the main thread").
from livekit.plugins import sarvam, silero, synthesia

from backend.models import SCREENING_KIND, ConversationRecord, EventType, Language
from backend.settings import Settings, get_settings
from voice.engine.kinds import get_kind
from voice.engine.speech_text import clean_for_speech, strip_leaked_tool_text
from voice.text_mode import TextConversation, openai_client

log = logging.getLogger("agenthire.worker")

TTS_LANGUAGE = {Language.TELUGU: "te-IN", Language.HINDI: "hi-IN", Language.ENGLISH: "en-IN"}
ANSWER_TIMEOUT_SECONDS = 75
# How long to wait for the other side to join the room at all. The back end dials the
# phone only once this worker is in the room, so a phone joins within seconds; a user
# in the browser may take a while to tap the orb.
JOIN_TIMEOUT_SECONDS = {"phone": 60, "browser": 300}
# At the time cap: how long the turn in progress plus a goodbye may take before the line is cut.
GOODBYE_SECONDS = 20


def backend_url() -> str:
    return os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def internal_headers(settings: Settings) -> dict[str, str]:
    token = settings.secrets.internal_api_token
    return {"X-Internal-Token": token} if token else {}


class EventSink:
    """Posts events to the back end in order, from any thread, without blocking the call."""

    def __init__(self, settings: Settings, job_id: str, conversation_id: str):
        self._settings = settings
        self._job_id = job_id
        self._conversation_id = conversation_id
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[tuple[EventType, dict[str, Any]] | None] = asyncio.Queue()
        self._task = asyncio.create_task(self._run())

    def emit(self, type_: EventType, payload: dict[str, Any]) -> None:
        # Called from the event loop and from the thread the conversation turn runs in.
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (type_, payload))

    async def close(self) -> None:
        # Queued the same way as `emit`, so it lands after every event already emitted. Put
        # straight on the queue, it overtook a "conversation ended" emitted just before it,
        # and the back end never heard that the call was over.
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        await self._task

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=10, headers=internal_headers(self._settings)) as client:
            while (item := await self._queue.get()) is not None:
                type_, payload = item
                body = {"job_id": self._job_id, "conversation_id": self._conversation_id,
                        "type": type_.value, "payload": payload}
                for attempt in range(4):
                    try:
                        response = await client.post(f"{backend_url()}/events", json=body)
                        response.raise_for_status()
                        break
                    except Exception as exc:  # the call goes on even if an event is lost
                        if attempt == 3:
                            log.warning("Event %s not delivered: %s", type_.value, exc)
                        await asyncio.sleep(0.5 * (attempt + 1))


# Where a sentence ends: a full stop, question or exclamation mark, or the Devanagari
# danda, followed by a space or a line break. Written as a code point, as in the engine.
_SENTENCE_END = re.compile("[.?!" + chr(0x0964) + r"](?=\s)|\n")
# The first piece of a reply may end at a clause (a comma or similar) once it is this long, so
# the voice starts before the whole first sentence is written. Measured on a live call: waiting
# for the full first sentence cost 1 to 4 s, while the voice itself needed only 0.2 s.
_CLAUSE_END = re.compile(r"[,;:](?=\s)")
FIRST_PIECE_CHARS = 40


def _next_cut(buffer: str, first: bool) -> int | None:
    """Where the next spoken piece ends in `buffer`, or None to wait for more text."""
    end = _SENTENCE_END.search(buffer)
    if end is not None:
        return end.end()
    if first:
        clause = _CLAUSE_END.search(buffer)
        if clause is not None and clause.end() >= 12:
            return clause.end()
        if len(buffer) >= FIRST_PIECE_CHARS:
            space = buffer.rfind(" ", 0, FIRST_PIECE_CHARS + 1)
            if space > 0:
                return space + 1
    return None


async def spoken_sentences(first: str, pieces: "asyncio.Queue[str | None]") -> AsyncIterator[str]:
    """The streamed reply, cleaned for speech, a piece at a time until the turn ends: the
    first piece as soon as a clause is written, then whole sentences. Each piece is cleaned
    whole, so nothing a voice cannot say slips through."""
    buffer, spoke = first, False
    while True:
        while (cut := _next_cut(buffer, first=not spoke)) is not None:
            sentence, buffer = buffer[:cut], buffer[cut:]
            spoken = clean_for_speech(strip_leaked_tool_text(sentence)).strip()
            if spoken:
                spoke = True
                yield spoken + " "
        piece = await pieces.get()
        if piece is None:
            break
        buffer += piece
    rest = clean_for_speech(strip_leaked_tool_text(buffer)).strip()
    if rest:
        yield rest


def _gap(start: float | None, end: float | None) -> str:
    return f"{end - start:.2f} s" if start is not None and end is not None else "-"


def stt_language(setting: str, language: Language) -> str:
    """Speech-to-text language. "call" means the conversation's own language (builder's
    decision, 22 Nov): auto-detect ("unknown") wrote Hindi speech in Gujarati, Punjabi,
    Odia, Bengali and Malayalam script on a real call. Sarvam cannot change it mid-call,
    so it stays the starting language even if the conversation switches."""
    return TTS_LANGUAGE[language] if setting == "call" else setting


async def start_avatar(settings: Settings, session: AgentSession, room: rtc.Room) -> Any:
    """Start the real-time avatar for a brief in the browser, or return None. She lip-syncs
    to our own voice; the engine still decides every word. Any failure falls back to plain
    audio, with the session's audio output reset so the agent is still heard."""
    avatar_settings, secrets = settings.avatar, settings.secrets
    if not (avatar_settings.enabled and avatar_settings.avatar_ids and secrets.avatar_api_key):
        return None
    started = time.perf_counter()
    try:
        avatar = synthesia.AvatarSession(
            synthesia.AvatarConfig(avatar_ids=list(avatar_settings.avatar_ids)),
            api_key=secrets.avatar_api_key, join_timeout=avatar_settings.join_timeout_seconds)
        await avatar.start(session, room=room, livekit_url=secrets.livekit_url,
                           livekit_api_key=secrets.livekit_api_key, livekit_api_secret=secrets.livekit_api_secret)
        log.info("Avatar joined %.1f s after starting", time.perf_counter() - started)
        return avatar
    except Exception as exc:
        log.warning("Avatar did not start, going on without it: %s: %s", type(exc).__name__, exc)
        session.output.audio = None  # let the room's own audio output take over again
        return None


class CallAgent(Agent):
    """No model here: each final transcript is handed to the conversation engine."""

    def __init__(self, on_turn: Any):
        super().__init__(instructions="Replies come from the AgentHire conversation engine.")
        self._on_turn = on_turn
        self._tasks: set[asyncio.Task] = set()

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        text = (new_message.text_content or "").strip()
        if text:
            # Not awaited: LiveKit waits for this hook before it handles the next turn.
            task = asyncio.create_task(self._on_turn(text))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        raise StopResponse()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()
    # Load heavy modules now: importing them during the first call stalled audio for about 0.2 s.
    import httpcore._async.http11  # noqa: F401
    import openai.lib.streaming  # noqa: F401

    from livekit.plugins import noise_cancellation  # noqa: F401


server = AgentServer(setup_fnc=prewarm)


async def wait_until_answered(ctx: JobContext, participant: rtc.RemoteParticipant) -> bool:
    """A dialled phone joins the room while ringing; wait until it is picked up."""
    answered = asyncio.Event()

    def check(*_: Any) -> None:
        if participant.attributes.get("sip.callStatus") == "active":
            answered.set()

    ctx.room.on("participant_attributes_changed", check)
    check()
    try:
        await asyncio.wait_for(answered.wait(), timeout=ANSWER_TIMEOUT_SECONDS)
        return True
    except TimeoutError:
        return False
    finally:
        ctx.room.off("participant_attributes_changed", check)


def turn_handling(settings: Settings, on_phone: bool, long_answers: bool = False) -> dict[str, Any]:
    """LiveKit's turn settings. The voice brief and screening calls wait longer before taking
    a pause as the end of a turn: people there describe or explain at length."""
    phone = settings.turn_taking.phone
    try:
        from livekit.agents import inference
        detection: Any = inference.TurnDetector()
    except Exception as exc:
        log.warning("Turn detector unavailable, using voice detection only: %s", exc)
        detection = "vad"
    handling: dict[str, Any] = {
        "turn_detection": detection,
        "interruption": {
            "mode": "vad",
            "min_words": phone.min_interruption_words,
            "min_duration": phone.min_interruption_seconds if on_phone else 0.5,
            # Keep what the person says over the opening, so their first words are not lost.
            "discard_audio_if_uninterruptible": False,
        },
    }
    timing = phone if on_phone and not long_answers else settings.turn_taking.long_answers
    handling["endpointing"] = {"min_delay": timing.min_endpointing_seconds,
                               "max_delay": timing.max_endpointing_seconds}
    return handling


def noise_cancellation(on_phone: bool) -> Any:
    try:
        from livekit.plugins import noise_cancellation as nc
        filter_ = nc.BVCTelephony() if on_phone else nc.BVC()
        log.info("Noise cancellation on: %s", type(filter_).__name__)
        return filter_
    except Exception as exc:
        log.warning("Noise cancellation unavailable: %s", exc)
        return None


@server.rtc_session(agent_name=get_settings().voice.agent_name)
async def entrypoint(ctx: JobContext) -> None:
    settings = get_settings()
    meta = json.loads(ctx.job.metadata or "{}")
    conversation_id, job_id = meta["conversation_id"], meta["job_id"]

    async with httpx.AsyncClient(timeout=10, headers=internal_headers(settings)) as client:
        response = await client.get(f"{backend_url()}/conversations/{conversation_id}")
        response.raise_for_status()
    record = ConversationRecord(**response.json()["record"])
    sink = EventSink(settings, job_id, conversation_id)
    log.info("Conversation %s (%s, %s), room %s", conversation_id, record.kind, record.language.value, ctx.room.name)

    await ctx.connect()
    convo = TextConversation(record, settings=settings, client=openai_client(settings), emit=sink.emit)

    async def _report_if_unfinished() -> None:
        # However this job ends - even before the call is answered - the back end hears
        # that the conversation is over, so its calling step never waits in vain (on a
        # real call the phone hung up before this worker joined, and nothing was reported).
        convo.close("call closed")
        await sink.close()

    ctx.add_shutdown_callback(_report_if_unfinished)
    # Prepare and check the opening while the phone rings, so it is ready the moment it is answered.
    prepare_started = time.perf_counter()
    opening_task = asyncio.create_task(asyncio.to_thread(convo.start, announce=False))

    join_timeout = JOIN_TIMEOUT_SECONDS.get(get_kind(record.kind).channel, 60)
    try:
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=join_timeout)
    except (asyncio.TimeoutError, RuntimeError) as exc:
        # Nobody came, or the room was closed first (LiveKit raises "room disconnected while
        # waiting for participant"). Report it here: the job may end before shutdown callbacks run.
        log.info("Nobody joined %s: %s", conversation_id, type(exc).__name__)
        convo.close("no answer")
        await sink.close()
        opening_task.cancel()
        ctx.shutdown(reason="nobody joined")
        return
    on_phone = participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
    if on_phone and not await wait_until_answered(ctx, participant):
        log.info("Not answered: %s", conversation_id)
        await opening_task
        convo.close("no answer")
        await sink.close()
        ctx.shutdown(reason="no answer")
        return
    answered_at = time.perf_counter()
    convo.restart_clock()  # the 3-minute cap counts from the answer, not from the ringing
    opening = await opening_task
    log.info("Opening ready %.1f s after dialling; waited %.1f s for it after the answer",
             answered_at - prepare_started, max(0.0, time.perf_counter() - answered_at))

    voice = settings.voice
    speaker, option = voice.voice_for(record.language.value)
    tts = sarvam.TTS(target_language_code=TTS_LANGUAGE[record.language], model=option.model, speaker=speaker)
    log.info("Voice: %s (%s, %s)", speaker, option.model, option.gender)
    session = AgentSession(
        stt=sarvam.STT(language=stt_language(voice.stt_language, record.language), model=voice.stt_model,
                       mode=voice.stt_mode),
        tts=tts, vad=ctx.proc.userdata["vad"],
        turn_handling=turn_handling(settings, on_phone, long_answers=record.kind == SCREENING_KIND),
    )
    turn_lock = asyncio.Lock()
    hanging_up = asyncio.Event()

    async def hang_up(reason: str) -> None:
        if hanging_up.is_set():
            return
        hanging_up.set()
        convo.close(reason)
        await asyncio.sleep(0.5)  # let the last words leave the line
        # Close the session before the room, so LiveKit does not try to write to a closed room.
        try:
            await session.aclose()
        except Exception as exc:
            log.warning("Session close: %s", exc)
        try:
            await ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
        except Exception as exc:
            log.warning("Could not close room %s: %s", ctx.room.name, exc)

    silence_task: asyncio.Task | None = None
    background: set[asyncio.Task] = set()

    def spawn(coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)
        return task

    def stop_silence_timer() -> None:
        if silence_task is not None and silence_task is not asyncio.current_task():
            silence_task.cancel()

    dead_air_used = False  # the dead-air nudge is used once per thing the person says

    def arm_silence_timer(spoken: str = "") -> None:
        """After the agent speaks: if it asked nothing, a short quiet makes it carry on
        (once), so there is no dead air; otherwise a long quiet counts as a silence."""
        nonlocal silence_task, dead_air_used
        stop_silence_timer()
        asked = spoken.rstrip().endswith("?")
        if spoken and not asked and not dead_air_used and not convo.state.nothing_left_to_find:
            dead_air_used = True
            silence_task = spawn(quiet_for(settings.turn_taking.dead_air_seconds, convo.keep_going))
        else:
            silence_task = spawn(quiet_for(settings.turn_taking.silence_seconds, convo.on_silence))

    async def quiet_for(seconds: float, then: Any) -> None:
        await asyncio.sleep(seconds)
        await run_turn(then)

    loop = asyncio.get_running_loop()
    stopped_at: float | None = None       # when the person stopped speaking
    transcript_at: float | None = None    # when their final transcript reached the engine
    first_words_at: float | None = None   # when the model's first words arrived

    # What the person said that no reply has taken yet. A person who pauses mid-thought is
    # heard as several short turns; any that arrive while a reply is in progress are joined
    # and answered once, not one by one.
    unanswered: list[str] = []

    async def run_turn(produce: Any, *args: Any, lines: list[str] | None = None) -> None:
        """One agent turn: the reply is computed off the event loop and spoken as it
        streams, a sentence at a time, so the first words are heard while the model is
        still writing the rest. Then hang up if the conversation ended, or start
        listening for a silence. With `lines`, the reply is to everything in it, taken
        once the turn's lock is held."""
        async with turn_lock:
            if convo.ended:
                return
            if lines is not None:
                if not lines:
                    return
                args = (" ".join(lines),)
                lines.clear()
            before = convo.state.reply_language
            pieces: asyncio.Queue[str | None] = asyncio.Queue()
            convo.on_text = lambda piece: loop.call_soon_threadsafe(pieces.put_nowait, piece)
            work = asyncio.ensure_future(asyncio.to_thread(produce, *args))
            work.add_done_callback(lambda _: loop.call_soon_threadsafe(pieces.put_nowait, None))
            first = await pieces.get()
            nonlocal first_words_at
            first_words_at = time.perf_counter()
            # The person's line has been read by now, so a language switch is already known:
            # change the voice before the first word is spoken.
            if convo.state.reply_language != before:
                new_speaker, new_option = voice.voice_for(convo.state.reply_language.value)
                tts.update_options(target_language_code=TTS_LANGUAGE[convo.state.reply_language],
                                   model=new_option.model, speaker=new_speaker)
                log.info("Voice switched to %s (%s)", new_speaker, new_option.model)
            if first is not None:
                await session.say(spoken_sentences(first, pieces))
            answer = await work
            if convo.ended:  # including a silence that ended a settled call without a reply
                await hang_up(convo.state.end_reason or "ended")
                return
            arm_silence_timer(answer or "")

    async def on_turn(text: str) -> None:
        nonlocal dead_air_used, transcript_at
        transcript_at = time.perf_counter()
        stop_silence_timer()
        dead_air_used = False
        unanswered.append(text)
        if len(unanswered) > 1:
            return  # a reply is already waiting for its turn, and will take this line too
        await run_turn(convo.reply, lines=unanswered)

    async def enforce_time_cap() -> None:
        """Wrap up near the end of the allowed time, and hang up at the cap whatever happens."""
        record_ = convo.state.record
        if record_.wrap_up_at_seconds is not None:
            await asyncio.sleep(max(0.0, record_.wrap_up_at_seconds - convo.state.seconds_elapsed))
            if not convo.ended and not turn_lock.locked():
                await run_turn(convo.wrap_up)
        await asyncio.sleep(max(0.0, record_.time_cap_seconds - convo.state.seconds_elapsed))
        if convo.ended:
            return
        # A short goodbye after the turn in progress, not a line cut mid-question (the
        # first live screening call was dropped while the agent was asking its last one).
        log.info("Time cap reached, saying goodbye: %s", conversation_id)
        try:
            await asyncio.wait_for(run_turn(convo.time_up), timeout=GOODBYE_SECONDS)
        except TimeoutError:
            log.warning("Goodbye took longer than %s s: %s", GOODBYE_SECONDS, conversation_id)
        await hang_up("time cap reached")  # does nothing if the goodbye already hung up

    @session.on("user_state_changed")
    def _user_state(ev: Any) -> None:
        nonlocal stopped_at
        if getattr(ev, "new_state", None) == "speaking":
            stop_silence_timer()
        elif getattr(ev, "old_state", None) == "speaking":
            stopped_at = time.perf_counter()

    @session.on("agent_state_changed")
    def _agent_state(ev: Any) -> None:
        # One line per turn: where the time went between the person stopping and the agent's
        # voice starting. Read it from data/worker.log to tune turn-taking and models.
        nonlocal stopped_at, transcript_at, first_words_at
        if getattr(ev, "new_state", None) != "speaking" or transcript_at is None:
            return
        now = time.perf_counter()
        log.info("Turn timing: stopped->transcript %s, transcript->first words %s, first words->voice %.2f s, "
                 "stopped->voice %s", _gap(stopped_at, transcript_at), _gap(transcript_at, first_words_at),
                 now - (first_words_at or now), _gap(stopped_at, now))
        stopped_at = transcript_at = first_words_at = None

    @session.on("metrics_collected")
    def _metrics(ev: Any) -> None:
        m = getattr(ev, "metrics", None)
        kind = type(m).__name__
        if kind == "EOUMetrics":
            log.info("End of turn: decided %.2f s after speech stopped (transcript ready at %.2f s)",
                     m.end_of_utterance_delay, m.transcription_delay)
        elif kind == "TTSMetrics" and getattr(m, "ttfb", -1) >= 0:
            log.info("Voice: first audio %.2f s after the text", m.ttfb)

    @session.on("close")
    def _closed(ev: Any) -> None:
        convo.close("the person hung up" if not convo.ended else convo.state.end_reason or "ended")

    async def _on_shutdown() -> None:
        for task in list(background):
            task.cancel()

    ctx.add_shutdown_callback(_on_shutdown)

    # The face of the agent in the voice brief: started before the session, as the plugin
    # requires, and only in the browser. If she does not come, the brief goes on with the orb.
    avatar = None if on_phone else await start_avatar(settings, session, ctx.room)
    await session.start(
        agent=CallAgent(on_turn), room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(noise_cancellation=noise_cancellation(on_phone)),
            # Listen to this person only: in the brief the avatar is a second participant.
            participant_identity=participant.identity,
            close_on_disconnect=True),
    )
    if avatar is not None:
        sink.emit(EventType.AVATAR_READY, {"provider": settings.avatar.provider})
    if on_phone:
        # A moment for the person to bring the phone to their ear.
        await asyncio.sleep(settings.turn_taking.phone.greeting_delay_seconds)
    spawn(enforce_time_cap())
    if opening:
        handle = session.say(opening, allow_interruptions=False)
        log.info("Opening started %.1f s after the answer", time.perf_counter() - answered_at)
        convo.opening_spoken()
        await handle
        if not convo.ended and not turn_lock.locked():
            arm_silence_timer(opening)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 1:
        sys.argv.append("dev")
    cli.run_app(server)
