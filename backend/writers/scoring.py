"""Scores one screening call against the approved scoring guide (docs/LLD.md, section 17).

Each question the candidate answered gets a score from 1 to 5 and the candidate's own words
it rests on, citing the transcript line. `backend.jobs.shortlist` then checks every quote
in code, as the call results are checked, and drops a score whose quote is not in what the
candidate said. Content only: never accent, fluency, grammar or language choice.
"""

from __future__ import annotations

import json
from typing import Any

from backend.models import TranscriptLine
from backend.settings import Settings

INSTRUCTIONS = """You are a fair, careful recruiter scoring a short first screening phone call.
You are given the screening questions, each with a guide to what a strong, an average and a weak answer contains, and the
call's transcript (AGENT is the recruiter's assistant, PERSON is the candidate; each line has a number).

For each question the candidate actually answered:
- score: 1 to 5 against that question's guide (5 strong, 3 average, 1 weak or no real answer).
- quote: the candidate's own words the score rests on, copied exactly from one PERSON line, and evidence_seq: that line's number.
- reason: one short plain sentence on why, about the content of the answer.
Leave out questions that were never asked or never answered. Judge only what was said: never accent, fluency, grammar,
confidence of speech or the language used, and never anything about the person rather than the answer.
summary: one or two plain sentences on how the candidate came across against the role, from the call only."""

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["scores", "summary"],
    "properties": {
        "summary": {"type": "string"},
        "scores": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["question", "score", "quote", "evidence_seq", "reason"],
            "properties": {"question": {"type": "integer"}, "score": {"type": "integer"},
                           "quote": {"type": "string"}, "evidence_seq": {"type": "integer"},
                           "reason": {"type": "string"}}}},
    },
}


def score_call(questions: list[dict[str, Any]], transcript: list[TranscriptLine], *, client: Any,
               settings: Settings) -> dict[str, Any]:
    """The model's scores for one call, before the quotes are checked."""
    guide = "\n".join(f"{i}. {q['question']}\n   strong: {q.get('strong', '')}\n   average: {q.get('average', '')}"
                      f"\n   weak: {q.get('weak', '')}" for i, q in enumerate(questions, start=1))
    lines = "\n".join(f"[{t.seq}] {t.speaker.upper()}: {t.text}" for t in transcript)
    response = client.chat.completions.create(
        model=settings.secrets.llm_model_smart, reasoning_effort="low",
        messages=[{"role": "system", "content": INSTRUCTIONS},
                  {"role": "user", "content": f"Screening questions:\n{guide}\n\nTranscript:\n{lines}"}],
        response_format={"type": "json_schema", "json_schema": {"name": "scores", "strict": True, "schema": SCHEMA}},
    )
    return json.loads(response.choices[0].message.content)
