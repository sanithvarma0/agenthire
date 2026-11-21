"""Builds the result of a call from its full transcript (docs/LLD.md, section 13).

This is the result the user sees. It is written after the call by a stronger
model that reads the whole conversation, so a slip during the call (a fact taken
too early, a later correction) is judged with everything in view. Every fact
cites the transcript line it came from, and `backend.guardrails.ground_call_result`
then checks each citation in code.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.models import (
    CallResult,
    CollectedFact,
    ConversationRecord,
    Event,
    EventType,
    Language,
    Outcome,
    TranscriptLine,
    outcome_meanings,
)
from backend.settings import Settings

INSTRUCTIONS = """You read the transcript of a phone call and record what it established.

Rules:
- Use only what the person (not the agent) said. The agent's words are context, never evidence.
- For each fact, quote the person's own words in said_as, copied from one line, and give that line's number in evidence_seq.
- Leave a fact out if the person never clearly answered it. A greeting, "tell me", or a question back is not an answer.
- A time given as "after X", "around X" or a range does answer when they can come: use the earliest time it allows, even if they add that they will confirm the exact time later.
- If they gave a day but no time of day, write only the date as YYYY-MM-DD. Never invent a time.
- If the person corrected themselves, use the corrected value and quote the correction.
- Normalise each value: money as a plain number of rupees, except a salary, which is written as said in lakhs per year (for example 12 LPA); a notice period as said (for example 30 days or 2 months); days and times as YYYY-MM-DD HH:MM, worked out from today's date given below; yes or no answers as yes or no; an answer to an open question as one or two plain English sentences saying what they told you, adding nothing; anything else as a short plain phrase in English.
- Choose the outcome that fits the whole call, by these meanings:
{outcomes}
- language_spoken is the language the person mostly used.
- do_not_call is true only if the person asked not to be called again.
- notes: one short sentence in English with anything else useful to the person deciding, such as conditions on the price; empty if nothing."""


def instructions(kind: str) -> str:
    """The writer's rules, with the outcomes of this kind of conversation. Every outcome of
    the kind may be chosen: a voicemail greeting is "spoken", so only the writer can tell
    it is still `no_answer`."""
    return INSTRUCTIONS.format(
        outcomes="\n".join(f"  - {outcome.value}: {meaning}" for outcome, meaning in outcome_meanings(kind).items()))


def transcript_from_events(events: list[Event]) -> list[TranscriptLine]:
    speakers = {EventType.AGENT_SAID.value: "agent", EventType.PERSON_SAID.value: "person"}
    return [
        TranscriptLine(seq=e.seq, speaker=speakers[e.type], text=str(e.payload.get("text", "")))
        for e in events if e.type in speakers and e.payload.get("text")
    ]


def result_schema(record: ConversationRecord) -> dict[str, Any]:
    fact_names = [f.name for f in record.facts_to_collect]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["outcome", "facts", "language_spoken", "do_not_call", "notes"],
        "properties": {
            "outcome": {"type": "string", "enum": [o.value for o in outcome_meanings(record.kind)]},
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "value", "said_as", "evidence_seq"],
                    "properties": {
                        "name": {"type": "string", "enum": fact_names},
                        "value": {"type": "string"},
                        "said_as": {"type": "string"},
                        "evidence_seq": {"type": "integer"},
                    },
                },
            },
            "language_spoken": {"type": "string", "enum": [lang.value for lang in Language]},
            "do_not_call": {"type": "boolean"},
            "notes": {"type": "string"},
        },
    }


def _request(record: ConversationRecord, transcript: list[TranscriptLine], now: datetime) -> str:
    facts = "\n".join(f"- {f.name}: {f.description}" for f in record.facts_to_collect)
    lines = "\n".join(f"[{line.seq}] {line.speaker.upper()}: {line.text}" for line in transcript)
    return (f"Today is {now:%A %Y-%m-%d}, and the time is {now:%H:%M}.\n\n"
            f"What the call was for: {record.goal}\n\nFacts to find:\n{facts}\n\nTranscript:\n{lines}")


def write_call_result(record: ConversationRecord, transcript: list[TranscriptLine], *, client: Any,
                      settings: Settings, now: datetime, live: CallResult | None = None) -> CallResult:
    """The call's result, before grounding. A call where the person said nothing
    is `no_answer` without asking a model."""
    if not any(line.speaker == "person" for line in transcript):
        return CallResult(outcome=Outcome.NO_ANSWER, do_not_call=bool(live and live.do_not_call))

    response = client.chat.completions.create(
        model=settings.secrets.llm_model_smart,
        messages=[{"role": "system", "content": instructions(record.kind)},
                  {"role": "user", "content": _request(record, transcript, now)}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "call_result", "strict": True, "schema": result_schema(record)}},
    )
    data = json.loads(response.choices[0].message.content)

    facts: dict[str, CollectedFact] = {}
    for item in data["facts"]:
        facts[item["name"]] = CollectedFact(  # one value per fact; a later item wins
            name=item["name"], value=item["value"], said_as=item["said_as"], evidence_seq=item["evidence_seq"])
    return CallResult(
        outcome=Outcome(data["outcome"]),
        facts=list(facts.values()),
        notes=data["notes"],
        language_spoken=Language(data["language_spoken"]),
        # A request not to be called again is never lost, whichever side noticed it.
        do_not_call=bool(data["do_not_call"]) or bool(live and live.do_not_call),
    )
