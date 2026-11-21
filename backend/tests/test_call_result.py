"""Tests for the call-result writer and the grounding check, with a fake model."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from backend.guardrails import check_fact, ground_call_result
from backend.models import CallResult, CollectedFact, Event, Language, Outcome, TranscriptLine
from backend.settings import load_settings
from backend.text_match import numbers, quote_in_line
from backend.writers.call_result import result_schema, transcript_from_events, write_call_result
from voice.engine.kinds import build_record

NOW = datetime(2026, 11, 21, 18, 45)

TRANSCRIPT = [
    TranscriptLine(seq=3, speaker="agent", text="అన్నా నమస్తే, మా ఇంట్లో tap leak అవుతోంది. వచ్చి చూస్తారా?"),
    TranscriptLine(seq=4, speaker="person", text="సరే, ఎల్లుండి సాయంత్రం నాలుగు గంటలకు వస్తాను."),
    TranscriptLine(seq=6, speaker="agent", text="visiting charge ఎంత అన్నా?"),
    TranscriptLine(seq=7, speaker="person", text="చూడటానికి రెండు వందలు. కాదు కాదు, సారీ, రెండు వందల యాభై."),
    TranscriptLine(seq=9, speaker="person", text="Ok, 10 AM ki vasta, charge 300."),
]


def record():
    return build_record("home_call", Language.TELUGU, time_cap_seconds=180,
                        shareable={"work": "tap leak", "area": "Kondapur"})


class FakeModel:
    def __init__(self, reply: dict | None = None):
        self.reply = reply
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        content = json.dumps(self.reply, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def model_reply(**overrides) -> dict:
    reply = {
        "outcome": "available",
        "facts": [
            {"name": "available", "value": "yes", "said_as": "ఎల్లుండి సాయంత్రం నాలుగు గంటలకు వస్తాను", "evidence_seq": 4},
            {"name": "earliest_time", "value": "2026-11-23 16:00", "said_as": "ఎల్లుండి సాయంత్రం నాలుగు గంటలకు",
             "evidence_seq": 4},
            {"name": "visiting_charge", "value": "250", "said_as": "రెండు వందల యాభై", "evidence_seq": 7},
        ],
        "language_spoken": "te",
        "do_not_call": False,
        "notes": "",
    }
    reply.update(overrides)
    return reply


# --- matching helpers -------------------------------------------------------

def test_quote_matching_handles_telugu_and_punctuation() -> None:
    assert quote_in_line("రెండు వందల యాభై", "చూడటానికి రెండు వందలు. కాదు కాదు, సారీ, రెండు వందల యాభై.")
    assert not quote_in_line("మూడు వందలు", "చూడటానికి రెండు వందలు.")


def test_numbers_ignore_separators() -> None:
    assert numbers("₹1,500 or 2000") == {1500, 2000}
    assert numbers("no digits here") == set()


# --- writer -----------------------------------------------------------------

def test_writer_returns_cited_facts() -> None:
    model = FakeModel(model_reply())
    result = write_call_result(record(), TRANSCRIPT, client=model, settings=load_settings(), now=NOW)
    assert result.outcome is Outcome.AVAILABLE
    assert result.fact("visiting_charge").value == "250"
    assert result.fact("earliest_time").evidence_seq == 4
    assert result.language_spoken is Language.TELUGU


def test_writer_is_told_today_and_uses_the_strong_model() -> None:
    model = FakeModel(model_reply())
    settings = load_settings()
    write_call_result(record(), TRANSCRIPT, client=model, settings=settings, now=NOW)
    sent = model.requests[0]
    assert sent["model"] == settings.secrets.llm_model_smart
    assert "Today is Saturday 2026-11-21" in sent["messages"][1]["content"]
    assert "[7] PERSON:" in sent["messages"][1]["content"] and "[3] AGENT:" in sent["messages"][1]["content"]
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert "Never invent a time" in sent["messages"][0]["content"]
    # The writer judges outcomes by the same meanings the live agent uses.
    assert "not_available: they cannot take the job" in sent["messages"][0]["content"]
    assert "declined: they refused to talk at all" in sent["messages"][0]["content"]


def test_schema_limits_fact_names_and_outcomes() -> None:
    schema = result_schema(record())
    item = schema["properties"]["facts"]["items"]["properties"]
    assert item["name"]["enum"] == ["available", "earliest_time", "visiting_charge"]
    assert "no_answer" in schema["properties"]["outcome"]["enum"]  # voicemail is still no answer


def test_nobody_spoke_means_no_answer_without_a_model_call() -> None:
    model = FakeModel()
    agent_only = [TranscriptLine(seq=1, speaker="agent", text="హలో?")]
    result = write_call_result(record(), agent_only, client=model, settings=load_settings(), now=NOW)
    assert result.outcome is Outcome.NO_ANSWER
    assert model.requests == []


def test_a_do_not_call_seen_during_the_call_is_kept() -> None:
    model = FakeModel(model_reply(outcome="declined", facts=[], do_not_call=False))
    live = CallResult(outcome=Outcome.DECLINED, do_not_call=True)
    result = write_call_result(record(), TRANSCRIPT, client=model, settings=load_settings(), now=NOW, live=live)
    assert result.do_not_call


def test_transcript_comes_from_spoken_events_only() -> None:
    def event(seq, type_, payload):
        return Event(id=seq, job_id="job_1", conversation_id="conv_1", seq=seq, type=type_, payload=payload,
                     created_at="2026-11-21T13:00:00")
    lines = transcript_from_events([
        event(1, "conversation_started", {}),
        event(2, "agent_said", {"text": "నమస్తే"}),
        event(3, "tool_called", {"name": "record_fact"}),
        event(4, "person_said", {"text": "చెప్పండి"}),
    ])
    assert [(l.seq, l.speaker) for l in lines] == [(2, "agent"), (4, "person")]


# --- grounding --------------------------------------------------------------

def test_good_facts_are_verified() -> None:
    model = FakeModel(model_reply())
    result = write_call_result(record(), TRANSCRIPT, client=model, settings=load_settings(), now=NOW)
    grounded, problems = ground_call_result(result, TRANSCRIPT)
    assert problems == []
    assert all(f.verified for f in grounded.facts)


def test_a_fact_quoting_the_agent_is_not_verified() -> None:
    ok, reason = check_fact("వచ్చి చూస్తారా", "yes", 3, TRANSCRIPT)
    assert not ok and reason == "cites the agent, not the person"


def test_a_quote_missing_from_its_line_is_not_verified() -> None:
    ok, reason = check_fact("మూడు వందలు", "300", 7, TRANSCRIPT)
    assert not ok and reason == "the quote is not in the cited line"


def test_a_line_that_does_not_exist_is_not_verified() -> None:
    ok, reason = check_fact("రెండు వందల యాభై", "250", 99, TRANSCRIPT)
    assert not ok and reason == "cites no line of this call"


def test_a_value_that_contradicts_the_spoken_number_is_not_verified() -> None:
    ok, reason = check_fact("charge 300", "350", 9, TRANSCRIPT)
    assert not ok and reason == "the value does not match the number the person said"
    assert check_fact("charge 300", "300", 9, TRANSCRIPT)[0]


def test_a_yes_quoted_from_a_line_with_a_time_is_verified() -> None:
    line = [TranscriptLine(seq=4, speaker="person", text="అవును అన్నా, రేపు 11 గంటలకు వస్తా.")]
    assert check_fact("అవును అన్నా, రేపు 11 గంటలకు వస్తా.", "yes", 4, line) == (True, "")


def test_a_twelve_hour_time_matches_its_twenty_four_hour_value() -> None:
    assert check_fact("10 AM ki vasta", "2026-11-22 10:00", 9, TRANSCRIPT)[0]
    line = [TranscriptLine(seq=1, speaker="person", text="sayantram 4 ki vasta")]
    assert check_fact("4 ki vasta", "2026-11-23 16:00", 1, line)[0]


def test_unverified_facts_stay_in_the_result_but_are_marked() -> None:
    result = CallResult(outcome=Outcome.AVAILABLE, facts=[
        CollectedFact(name="visiting_charge", value="300", said_as="మూడు వందలు", evidence_seq=7),
        CollectedFact(name="earliest_time", value="2026-11-23 16:00", said_as="నాలుగు గంటలకు", evidence_seq=4),
    ])
    grounded, problems = ground_call_result(result, TRANSCRIPT)
    assert [f.verified for f in grounded.facts] == [False, True]
    assert problems == ["visiting_charge: the quote is not in the cited line"]
