"""Tests for the storage layer and the settings loader."""

from __future__ import annotations

import pytest

from backend.db import Database, new_id
from backend.models import JobStep, Person, PersonRole, Side
from backend.settings import load_settings


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    yield database
    database.close()


def make_person(job_id: str, phone: str) -> Person:
    return Person(id=new_id("per"), job_id=job_id, role=PersonRole.PROVIDER, name="Test Provider",
                  phone=phone, source="test", rating=4.8, review_count=12)


def test_job_starts_at_briefing_and_moves(db: Database) -> None:
    job_id = db.create_job(Side.HOME)
    assert db.get_job(job_id)["step"] == JobStep.BRIEFING
    db.set_job_brief(job_id, {"service": "electrician", "area": "Kondapur"})
    db.set_job_step(job_id, JobStep.FINDING)
    job = db.get_job(job_id)
    assert job["step"] == JobStep.FINDING
    assert job["brief"]["area"] == "Kondapur"


def test_events_are_numbered_per_job_in_order(db: Database) -> None:
    first, second = db.create_job(Side.HOME), db.create_job(Side.HOME)
    assert db.add_event(first, "agent_said", {"text": "a"}).seq == 1
    assert db.add_event(first, "person_said", {"text": "b"}).seq == 2
    assert db.add_event(second, "agent_said", {"text": "c"}).seq == 1
    assert [e.type for e in db.list_events(first)] == ["agent_said", "person_said"]
    assert [e.seq for e in db.list_events(first, after_seq=1)] == [2]


def test_event_payload_keeps_indian_scripts(db: Database) -> None:
    job_id = db.create_job(Side.HOME)
    db.add_event(job_id, "person_said", {"text": "రేపు ఉదయం వస్తాను"})
    assert db.list_events(job_id)[0].payload["text"] == "రేపు ఉదయం వస్తాను"


def test_only_ticked_people_are_approved(db: Database) -> None:
    job_id = db.create_job(Side.HOME)
    ticked, unticked = make_person(job_id, "+911111111111"), make_person(job_id, "+912222222222")
    db.add_person(ticked)
    db.add_person(unticked)
    db.approve_people(job_id, [ticked.id])
    assert db.is_approved(job_id, ticked.phone)
    assert not db.is_approved(job_id, unticked.phone)
    assert [p.id for p in db.list_people(job_id, approved_only=True)] == [ticked.id]


def test_approval_does_not_carry_across_jobs(db: Database) -> None:
    first, second = db.create_job(Side.HOME), db.create_job(Side.HOME)
    person = make_person(first, "+911111111111")
    db.add_person(person)
    db.approve_people(first, [person.id])
    assert not db.is_approved(second, person.phone)


def test_facts_are_updated_in_place(db: Database) -> None:
    db.set_fact("provider", "+911111111111", "language_spoken", "te")
    db.set_fact("provider", "+911111111111", "language_spoken", "hi")
    db.set_fact("provider", "+911111111111", "do_not_call", "true")
    assert db.get_facts("provider", "+911111111111") == {"language_spoken": "hi", "do_not_call": "true"}
    assert db.get_facts("provider", "+919999999999") == {}


def test_conversation_result_round_trip(db: Database) -> None:
    job_id = db.create_job(Side.HOME)
    conversation_id = db.create_conversation(job_id, "home_call", "te", {"goal": "find out availability"})
    db.set_conversation_status(conversation_id, "active")
    db.set_conversation_result(conversation_id, {"outcome": "available"})
    db.set_conversation_status(conversation_id, "ended")
    conversation = db.get_conversation(conversation_id)
    assert conversation["status"] == "ended"
    assert conversation["started_at"] and conversation["ended_at"]
    assert conversation["result"] == {"outcome": "available"}
    assert db.count_calls(job_id, "home_call") == 1


def test_blocked_conversations_do_not_count_as_calls(db: Database) -> None:
    job_id = db.create_job(Side.HOME)
    conversation_id = db.create_conversation(job_id, "home_call", "te", {})
    db.set_conversation_status(conversation_id, "blocked")
    assert db.count_calls(job_id, "home_call") == 0


def test_settings_load_product_rules() -> None:
    settings = load_settings()
    assert settings.calling.time_cap_seconds == 180
    assert settings.calling.max_calls_per_job == 3
    assert settings.providers.max_shown == 5
    assert settings.turn_taking.phone.min_interruption_words == 2


def test_test_mode_defaults_to_on(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TEST_MODE", raising=False)
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    assert load_settings(env_path=empty_env).test_mode is True
