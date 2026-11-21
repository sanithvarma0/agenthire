"""Tests for the comparison writer's rules that need no model: who can be recommended,
and that the reason quotes no number nobody said."""

from __future__ import annotations

from datetime import datetime

from backend.settings import load_settings
from backend.writers.comparison import Candidate, plain_reason, reason_is_grounded, write_comparison

NOW = datetime(2026, 11, 21, 23, 45)
A = Candidate(person_id="a", name="Power Electrician", outcome="available", earliest_time="2026-11-22 10:00",
              visiting_charge="800", distance_km=2.4, rating=4.9, review_count=69)
B = Candidate(person_id="b", name="Vicky", outcome="available", earliest_time="2026-11-22 17:00",
              visiting_charge="1000", distance_km=1.8, rating=5.0, review_count=19)
BUSY = Candidate(person_id="c", name="Busy Electricals", outcome="not_available")


class NoModel:
    @property
    def chat(self):  # pragma: no cover - must not be reached
        raise AssertionError("no model call expected")


def test_nobody_who_can_come_means_no_recommendation() -> None:
    result = write_comparison([BUSY], client=NoModel(), settings=load_settings(), now=NOW)
    assert result.recommended_person_id is None and "None of the providers" in result.reasoning


def test_one_who_can_come_is_recommended_without_a_model() -> None:
    result = write_comparison([BUSY, A], client=NoModel(), settings=load_settings(), now=NOW)
    assert result.recommended_person_id == "a" and result.reasoning == "Only Power Electrician can take the job."


def test_the_reason_may_only_use_numbers_from_the_facts() -> None:
    assert reason_is_grounded("Power Electrician can come tomorrow at 10 AM for 800 rupees.", [A, B])
    assert reason_is_grounded("Vicky comes at 5 PM, 1.8 km away.", [A, B])   # 17:00 said as 5 PM
    assert not reason_is_grounded("Power Electrician can come at 7 AM for 300 rupees.", [A, B])
    assert plain_reason(A, NOW) == "Power Electrician can come tomorrow at 10 AM and charges 800 rupees to visit."
    assert plain_reason(B, NOW).startswith("Vicky can come tomorrow at 5 PM")
