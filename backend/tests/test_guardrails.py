"""Tests for the dialling guardrails and the back end's call placement."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.calls import place_call
from backend.db import Database, new_id
from backend.events import EventBus
from backend.guardrails import DialDecision, can_dial, normalise_phone, within_calling_hours
from backend.main import create_app
from backend.models import Language, Person, PersonRole, Side
from backend.settings import load_settings
from voice.engine.kinds import build_record

IST = timezone(timedelta(hours=5, minutes=30))
NOON = datetime(2026, 11, 22, 12, 0, tzinfo=IST)
NIGHT = datetime(2026, 11, 22, 21, 30, tzinfo=IST)
OWN = "+919000000001"
PROVIDER = "+919111111111"


class FakeDialler:
    def __init__(self, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    async def dial(self, *, room, metadata, to):
        if self.fail:
            raise RuntimeError("trunk unavailable")
        self.calls.append({"room": room, "metadata": metadata, "to": to})


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    yield database
    database.close()


def settings(test_mode: bool = False):
    s = load_settings()
    s.test_mode = test_mode
    s.allowed_numbers = [OWN]
    s.demo_route_phone = OWN
    return s


def job_with(db: Database, *phones: str, approve: bool = True) -> tuple[str, list[Person]]:
    job_id = db.create_job(Side.HOME)
    people = []
    for phone in phones:
        person = Person(id=new_id("per"), job_id=job_id, role=PersonRole.PROVIDER, name="P", phone=phone,
                        source="test")
        db.add_person(person)
        people.append(person)
    if approve:
        db.approve_people(job_id, [p.id for p in people])
    return job_id, people


def record():
    return build_record("home_call", Language.TELUGU, time_cap_seconds=180,
                        shareable={"work": "fan", "area": "Madhapur"})


# --- phone numbers ----------------------------------------------------------

@pytest.mark.parametrize("raw", ["+91 91111 11111", "091111 11111", "9111111111", "91-9111111111", "+919111111111"])
def test_numbers_are_normalised(raw: str) -> None:
    assert normalise_phone(raw) == PROVIDER


# --- the five checks --------------------------------------------------------

def test_an_approved_number_in_hours_rings_the_provider(db: Database) -> None:
    job_id, _ = job_with(db, PROVIDER)
    decision = can_dial(PROVIDER, job_id, db=db, settings=settings(), now=NOON)
    assert decision == DialDecision(True, "", PROVIDER, False)


def test_test_mode_routes_every_call_to_the_builder(db: Database) -> None:
    job_id, _ = job_with(db, PROVIDER, OWN)
    routed = can_dial(PROVIDER, job_id, db=db, settings=settings(test_mode=True), now=NOON)
    assert routed == DialDecision(True, "", OWN, True)
    own = can_dial(OWN, job_id, db=db, settings=settings(test_mode=True), now=NOON)
    assert own == DialDecision(True, "", OWN, False)


def test_test_mode_needs_a_routing_number_of_the_builders_own(db: Database) -> None:
    job_id, _ = job_with(db, PROVIDER)
    s = settings(test_mode=True)
    for route in ("", PROVIDER):  # missing, or a stranger's number
        s.demo_route_phone = route
        decision = can_dial(PROVIDER, job_id, db=db, settings=s, now=NOON)
        assert not decision.allowed and decision.reason.startswith("test mode is on, but DEMO_ROUTE_PHONE")


def test_an_unapproved_number_is_refused(db: Database) -> None:
    job_id, _ = job_with(db, PROVIDER, approve=False)
    decision = can_dial(PROVIDER, job_id, db=db, settings=settings(), now=NOON)
    assert not decision.allowed and decision.reason == "the user has not approved this number for this job"


def test_approval_is_matched_whatever_the_number_format(db: Database) -> None:
    job_id, _ = job_with(db, "+91 91111 11111")
    assert can_dial("9111111111", job_id, db=db, settings=settings(), now=NOON).allowed


def test_calls_outside_hours_are_refused_unless_the_builder_answers(db: Database) -> None:
    job_id, _ = job_with(db, PROVIDER, OWN)
    decision = can_dial(PROVIDER, job_id, db=db, settings=settings(), now=NIGHT)
    assert not decision.allowed and decision.reason.startswith("outside calling hours")
    assert can_dial(OWN, job_id, db=db, settings=settings(), now=NIGHT).allowed
    # In test mode the provider's call rings the builder, so the hour does not matter.
    assert can_dial(PROVIDER, job_id, db=db, settings=settings(test_mode=True), now=NIGHT).allowed


def test_calling_hours_edges() -> None:
    s = settings()
    assert within_calling_hours(s, datetime(2026, 11, 22, 9, 0, tzinfo=IST))
    assert not within_calling_hours(s, datetime(2026, 11, 22, 8, 59, tzinfo=IST))
    assert within_calling_hours(s, datetime(2026, 11, 22, 19, 59, tzinfo=IST))
    assert not within_calling_hours(s, datetime(2026, 11, 22, 20, 0, tzinfo=IST))
    # A time given in another zone is converted first: 06:30 UTC is noon in India.
    assert within_calling_hours(s, datetime(2026, 11, 22, 6, 30, tzinfo=timezone.utc))


def test_a_do_not_call_number_is_refused(db: Database) -> None:
    job_id, _ = job_with(db, PROVIDER)
    db.set_fact("provider", PROVIDER, "do_not_call", "true")
    decision = can_dial(PROVIDER, job_id, db=db, settings=settings(), now=NOON)
    assert not decision.allowed and decision.reason == "this number asked not to be called again"


def test_the_job_call_cap_is_enforced(db: Database) -> None:
    job_id, _ = job_with(db, PROVIDER)
    for _ in range(3):
        db.create_conversation(job_id, "home_call", "te", {})
    decision = can_dial(PROVIDER, job_id, db=db, settings=settings(), now=NOON)
    assert not decision.allowed and decision.reason == "this job has used all 3 of its calls"


def test_checks_run_in_order(db: Database) -> None:
    # Test mode without a routing number, unapproved, at night: the test-mode refusal is reported.
    job_id, _ = job_with(db, PROVIDER, approve=False)
    s = settings(test_mode=True)
    s.demo_route_phone = ""
    assert can_dial(PROVIDER, job_id, db=db, settings=s, now=NIGHT).reason.startswith("test mode")


def test_a_missing_number_is_refused(db: Database) -> None:
    job_id, _ = job_with(db, PROVIDER)
    assert can_dial("", job_id, db=db, settings=settings(), now=NOON) == DialDecision(False, "no phone number")


# --- placing calls ----------------------------------------------------------

def test_a_refused_call_never_reaches_livekit(db: Database) -> None:
    job_id, (person,) = job_with(db, PROVIDER, approve=False)
    dialler, bus = FakeDialler(), EventBus(db)
    conversation_id, reason = asyncio.run(place_call(db=db, bus=bus, settings=settings(), dialler=dialler,
                                                     job_id=job_id, person=person, record=record(), now=NOON))
    assert reason == "the user has not approved this number for this job"
    assert dialler.calls == []
    assert db.get_conversation(conversation_id)["status"] == "blocked"
    event = db.list_events(job_id)[-1]
    assert event.type == "guardrail_blocked" and event.payload["reason"] == reason
    assert db.count_calls(job_id, "home_call") == 0  # a refused call does not use up the job's calls


def test_an_allowed_call_is_dialled_with_the_conversation(db: Database) -> None:
    job_id, (person,) = job_with(db, "+91 91111 11111")
    dialler = FakeDialler()
    conversation_id, reason = asyncio.run(place_call(db=db, bus=EventBus(db), settings=settings(), dialler=dialler,
                                                     job_id=job_id, person=person, record=record(), now=NOON))
    assert reason is None
    assert dialler.calls == [{"room": f"call-{conversation_id}", "to": PROVIDER,
                              "metadata": {"conversation_id": conversation_id, "job_id": job_id}}]
    conversation = db.get_conversation(conversation_id)
    assert conversation["status"] == "active" and conversation["person_id"] == person.id
    assert conversation["record"]["kind"] == "home_call"


def test_a_routed_call_rings_the_builder_and_is_marked(db: Database) -> None:
    job_id, (person,) = job_with(db, PROVIDER)
    dialler = FakeDialler()
    conversation_id, reason = asyncio.run(place_call(db=db, bus=EventBus(db), settings=settings(test_mode=True),
                                                     dialler=dialler, job_id=job_id, person=person,
                                                     record=record(), now=NIGHT))
    assert reason is None
    assert dialler.calls[0]["to"] == OWN
    assert db.get_conversation(conversation_id)["routed_to"] == OWN
    assert db.get_conversation(conversation_id)["person_id"] == person.id  # still the provider's conversation
    assert [e.type for e in db.list_events(job_id)] == ["call_routed"]


def test_a_fourth_call_is_refused(db: Database) -> None:
    job_id, people = job_with(db, PROVIDER, "+919222222222", "+919333333333", "+919444444444")
    dialler, bus = FakeDialler(), EventBus(db)
    reasons = [asyncio.run(place_call(db=db, bus=bus, settings=settings(), dialler=dialler, job_id=job_id,
                                      person=p, record=record(), now=NOON))[1] for p in people]
    assert reasons[:3] == [None, None, None]
    assert reasons[3] == "this job has used all 3 of its calls"
    assert len(dialler.calls) == 3


def test_a_failed_dial_is_reported_and_not_counted(db: Database) -> None:
    job_id, (person,) = job_with(db, PROVIDER)
    conversation_id, reason = asyncio.run(place_call(db=db, bus=EventBus(db), settings=settings(),
                                                     dialler=FakeDialler(fail=True), job_id=job_id, person=person,
                                                     record=record(), now=NOON))
    assert reason.startswith("the call could not be placed")
    assert db.count_calls(job_id, "home_call") == 0


def test_the_dev_endpoint_needs_test_mode(db: Database) -> None:
    body = {"to": OWN, "calling": "Test Electricals", "work": "fan", "area": "Madhapur"}
    off = TestClient(create_app(settings=settings(test_mode=False), database=db, dialler=FakeDialler()))
    assert off.post("/dev/test-call", json=body).status_code == 403
    dialler = FakeDialler()
    on = TestClient(create_app(settings=settings(test_mode=True), database=db, dialler=dialler))
    reply = on.post("/dev/test-call", json=body).json()
    assert reply["refused"] is None and dialler.calls[0]["to"] == OWN
    # Even the development endpoint cannot reach a stranger: test mode sends the call to the builder.
    assert on.post("/dev/test-call", json={**body, "to": PROVIDER}).json()["refused"] is None
    assert dialler.calls[-1]["to"] == OWN


def test_a_hindi_quote_matches_despite_the_full_stop() -> None:
    # From a real call: "10 बजे तक" was refused because the line ended in a danda.
    from backend.text_match import quote_in_line, words
    assert words("10 बजे तक।") == ["10", "बजे", "तक"]
    assert quote_in_line("10 बजे तक", "10 बजे तक।")
    assert quote_in_line("1000 तक होगा", "हाँ, 1000 तक होगा।")
