"""The worker's event sink must deliver every event emitted before it closes, in order.
On a real call, closing put its stop marker ahead of "conversation ended", so the back
end never heard that the call was over."""

from __future__ import annotations

import asyncio

import voice.worker as worker
from backend.models import EventType
from backend.settings import load_settings


class FakeClient:
    posted: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json):
        FakeClient.posted.append(json["type"])

        class Response:
            def raise_for_status(self):
                return None

        return Response()


def test_events_emitted_just_before_closing_are_still_delivered(monkeypatch) -> None:
    monkeypatch.setattr(worker.httpx, "AsyncClient", FakeClient)
    FakeClient.posted = []

    async def run() -> None:
        sink = worker.EventSink(load_settings(), "job_1", "conv_1")
        sink.emit(EventType.CONVERSATION_STARTED, {})
        sink.emit(EventType.CONVERSATION_ENDED, {"reason": "no answer"})  # emitted, then closed at once
        await sink.close()

    asyncio.run(run())
    assert FakeClient.posted == ["conversation_started", "conversation_ended"]


def test_an_agent_line_waits_for_its_voice(monkeypatch) -> None:
    # On screen, the whole line appeared about a second before it was heard.
    monkeypatch.setattr(worker.httpx, "AsyncClient", FakeClient)
    FakeClient.posted = []

    async def run() -> list[list[str]]:
        sink = worker.EventSink(load_settings(), "job_1", "conv_1")
        seen = []
        sink.emit(EventType.PERSON_SAID, {"text": "hello"})
        sink.emit(EventType.AGENT_SAID, {"text": "hi"})
        await asyncio.sleep(0.05)
        seen.append(list(FakeClient.posted))  # held: the voice has not started
        sink.voice_started()
        await asyncio.sleep(0.05)
        seen.append(list(FakeClient.posted))
        sink.emit(EventType.AGENT_SAID, {"text": "while speaking"})  # voice already playing: at once
        await asyncio.sleep(0.05)
        seen.append(list(FakeClient.posted))
        sink.voice_stopped()
        sink.emit(EventType.AGENT_SAID, {"text": "never voiced"})
        sink.emit(EventType.CONVERSATION_ENDED, {"reason": "x"})  # releases it first, order kept
        await sink.close()
        return seen

    seen = asyncio.run(run())
    assert seen[0] == ["person_said"]
    assert seen[1] == ["person_said", "agent_said"]
    assert seen[2] == ["person_said", "agent_said", "agent_said"]
    assert FakeClient.posted == ["person_said", "agent_said", "agent_said", "agent_said", "conversation_ended"]


def test_a_held_line_is_delivered_on_close(monkeypatch) -> None:
    monkeypatch.setattr(worker.httpx, "AsyncClient", FakeClient)
    FakeClient.posted = []

    async def run() -> None:
        sink = worker.EventSink(load_settings(), "job_1", "conv_1")
        sink.emit(EventType.AGENT_SAID, {"text": "goodbye"})
        await sink.close()

    asyncio.run(run())
    assert FakeClient.posted == ["agent_said"]


def test_a_streamed_reply_is_spoken_a_sentence_at_a_time() -> None:
    async def run() -> list[str]:
        pieces: asyncio.Queue = asyncio.Queue()
        for piece in ["సరే అన్నా, ", "రేపు 11కి. Visiting ", "charge ఎంత", " అవుతుంది?", None]:
            pieces.put_nowait(piece)
        first = await pieces.get()
        return [s async for s in worker.spoken_sentences(first, pieces)]

    assert asyncio.run(run()) == ["సరే అన్నా, రేపు 11కి. ", "Visiting charge ఎంత అవుతుంది?"]


def test_tool_text_in_a_streamed_reply_is_never_spoken() -> None:
    async def run() -> list[str]:
        pieces: asyncio.Queue = asyncio.Queue()
        for piece in ['"name":"available","value":"yes"\n', "అవును అన్నా.", None]:
            pieces.put_nowait(piece)
        first = await pieces.get()
        return [s async for s in worker.spoken_sentences(first, pieces)]

    assert "available" not in " ".join(asyncio.run(run()))


def test_a_tool_call_written_as_a_function_is_never_spoken() -> None:
    # From an eval run: the agent's whole turn was "functions.record fact( )".
    from voice.engine.speech_text import strip_leaked_tool_text
    assert strip_leaked_tool_text("functions.record fact( )") == ""
    assert "functions" not in strip_leaked_tool_text("ठीक है। functions.record_fact() कब आएँगे?")


def test_speech_to_text_uses_the_call_language() -> None:
    from backend.models import Language
    assert worker.stt_language("call", Language.HINDI) == "hi-IN"
    assert worker.stt_language("call", Language.TELUGU) == "te-IN"
    assert worker.stt_language("unknown", Language.TELUGU) == "unknown"  # auto-detect, if chosen again


def test_a_long_first_sentence_starts_speaking_at_its_first_clause() -> None:
    # Measured on a live call: waiting for the whole first sentence cost 1 to 4 s.
    async def run() -> list[str]:
        pieces: asyncio.Queue = asyncio.Queue()
        for piece in ["మేము Indira Nagar, Gachibowli నుంచి మాట్లాడుతున్నాం, ", "ఇంట్లో fan పని చేయట్లేదు, ",
                      "ఒకసారి వచ్చి చూస్తారా?", None]:
            pieces.put_nowait(piece)
        first = await pieces.get()
        return [s async for s in worker.spoken_sentences(first, pieces)]

    spoken = asyncio.run(run())
    assert spoken[0] == "మేము Indira Nagar, "  # spoken before the sentence is finished
    assert "".join(spoken).replace("  ", " ").strip().endswith("ఒకసారి వచ్చి చూస్తారా?")
