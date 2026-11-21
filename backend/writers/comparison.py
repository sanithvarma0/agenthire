"""Compares the providers called for a job and recommends one (docs/LLD.md, section 13).

Only providers who can come are recommended. With one, it is that one; with two or
more, a model weighs when they can come, the visiting charge, distance and reviews,
and gives one sentence of reasoning. Every number in that sentence must appear in
the facts it was given, as with call results; otherwise a plain reason is built
from the facts instead, so the screen never shows a number nobody said.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.models import Comparison
from backend.settings import Settings
from backend.text_match import numbers

INSTRUCTIONS = """You help someone choose which local provider to book for a job at their home.
You get each provider who can take the job: when they can come, their visiting charge, how far away they are, and their rating.
Pick the one most people would book: an earlier visit matters most for something broken at home, unless it is only an hour or two earlier and costs much more; then a lower visiting charge; then nearness and good reviews. Use judgement when these pull different ways.
reason: one sentence of at most 20 words in plain English saying why, naming the facts that decide it. Say days and times the way a person would ("tomorrow at 10 AM"), never as stored ("2026-11-22 10:00"). Use only the facts given; no other numbers."""


class Candidate(BaseModel):
    """One provider as the comparison sees them: the checked result and the listing."""
    person_id: str
    name: str
    outcome: str
    earliest_time: str | None = None
    visiting_charge: str | None = None
    notes: str = ""
    distance_km: float | None = None
    rating: float | None = None
    review_count: int | None = None


def write_comparison(candidates: list[Candidate], *, client: Any, settings: Settings, now: datetime) -> Comparison:
    able = [c for c in candidates if c.outcome == "available"]
    if not able:
        return Comparison(rows=[], reasoning="None of the providers called can take the job.")
    if len(able) == 1:
        return Comparison(rows=[], recommended_person_id=able[0].person_id,
                          reasoning=f"Only {able[0].name} can take the job.")

    schema = {
        "type": "object", "additionalProperties": False, "required": ["person_id", "reason"],
        "properties": {"person_id": {"type": "string", "enum": [c.person_id for c in able]},
                       "reason": {"type": "string"}},
    }
    facts = [c.model_dump(exclude={"outcome"}) for c in able]
    response = client.chat.completions.create(
        model=settings.secrets.llm_model_smart, reasoning_effort="low",
        messages=[{"role": "system", "content": INSTRUCTIONS},
                  {"role": "user", "content": f"Now: {now:%A %Y-%m-%d %H:%M}\n\n"
                                              + json.dumps(facts, ensure_ascii=False, indent=1)}],
        response_format={"type": "json_schema", "json_schema": {"name": "comparison", "strict": True, "schema": schema}},
    )
    data = json.loads(response.choices[0].message.content)
    chosen = next(c for c in able if c.person_id == data["person_id"])
    reason = data["reason"].strip()
    if not reason or not reason_is_grounded(reason, able):
        reason = plain_reason(chosen, now)
    return Comparison(rows=[], recommended_person_id=chosen.person_id, reasoning=reason)


def reason_is_grounded(reason: str, candidates: list[Candidate]) -> bool:
    """Every number in the reason appears in the facts the model was given."""
    known: set[int] = set()
    for c in candidates:
        for value in (c.earliest_time, c.visiting_charge, c.notes, c.distance_km, c.rating, c.review_count):
            if value is not None:
                known |= numbers(str(value))
        if c.earliest_time:  # "2026-11-22 17:00" may be said as 5 PM
            known |= {n - 12 for n in numbers(c.earliest_time) if 12 < n < 24}
    return numbers(reason) <= known


def spoken_time(value: str, now: datetime) -> str:
    """ "2026-11-22 10:00" as "tomorrow at 10 AM"; anything else as given."""
    try:
        when = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return value
    days = (when.date() - now.date()).days
    day = {0: "today", 1: "tomorrow"}.get(days, f"on {when:%A}" if 1 < days < 7 else f"on {when:%d %b}")
    hour = when.hour % 12 or 12
    minutes = f":{when:%M}" if when.minute else ""
    return f"{day} at {hour}{minutes} {'AM' if when.hour < 12 else 'PM'}"


def plain_reason(chosen: Candidate, now: datetime) -> str:
    parts = [p for p in (chosen.earliest_time and f"can come {spoken_time(chosen.earliest_time, now)}",
                         chosen.visiting_charge and f"charges {chosen.visiting_charge} rupees to visit") if p]
    return f"{chosen.name} " + (" and ".join(parts) if parts else "can take the job") + "."
