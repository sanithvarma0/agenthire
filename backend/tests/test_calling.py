"""Tests for the calling step: providers are called one at a time in rank order,
each result is written and grounded, and Skip and Stop work. The phone line, the
voice worker, Google and the model are all faked."""

from __future__ import annotations

import asyncio
import json
import re
import time
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from backend.db import Database
from backend.main import create_app
from backend.models import EventType
from backend.settings import load_settings
from backend.tests.test_jobs import FIVE, START, fake_google

OWN = "+919000000001"


class FakeModel:
    """Answers the brief writer and the call-result writer. The result cites the
    person's line that names the charge, as the real writer must."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        name = kwargs["response_format"]["json_schema"]["name"]
        if name == "brief":
            answer = {"service": "electrician", "work": "Kitchen light flickers.", "understood": True}
        elif name == "comparison":
            schema = kwargs["response_format"]["json_schema"]["schema"]
            first = schema["properties"]["person_id"]["enum"][0]
            answer = {"person_id": first, "reason": "Can come and charges 500 rupees to visit."}
        else:
            text = kwargs["messages"][-1]["content"]
            lines = [(int(m[1]), m[2]) for m in re.finditer(r"\[(\d+)\] PERSON: (.*)", text)]
            if not any("500" in said for _, said in lines):
                answer = {"outcome": "not_available", "language_spoken": "te", "do_not_call": False, "notes": "",
                          "facts": []}
                message = SimpleNamespace(content=json.dumps(answer), tool_calls=None)
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])
            seq, said = next((s, w) for s, w in lines if "500" in w)
            answer = {"outcome": "available", "language_spoken": "te", "do_not_call": False, "notes": "",
                      "facts": [{"name": "visiting_charge", "value": "500", "said_as": said, "evidence_seq": seq}]}
        message = SimpleNamespace(content=json.dumps(answer), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeSms:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, *, to, body):
        self.sent.append({"to": to, "body": body})
        return "SM_fake"


class FakeLine:
    """Stands in for LiveKit and the voice worker: a dialled call 'talks' and then
    reports that it ended, unless it is told to hang (to test Skip)."""

    def __init__(self, hang: set[int] = frozenset(), refuse: set[int] = frozenset()):
        self.refuse = refuse  # call numbers (1-based) where the provider says they cannot come
        self.dialled: list[str] = []
        self.hung_up: list[str] = []
        self.hang = hang  # call numbers (1-based) that never end by themselves
        self.bus = None

    async def dial(self, *, room, metadata, to):
        self.dialled.append(to)
        if len(self.dialled) not in self.hang:
            can = len(self.dialled) not in self.refuse
            asyncio.get_running_loop().create_task(self._talk(metadata["job_id"], metadata["conversation_id"], can))

    async def _talk(self, job_id: str, conversation_id: str, can: bool = True):
        said = "అవునండి, 500 rupees అవుతుంది" if can else "ఇప్పుడు రాలేనండి"
        for type_, payload in [(EventType.AGENT_SAID, {"text": "నమస్కారం అన్నా"}),
                               (EventType.PERSON_SAID, {"text": said}),
                               (EventType.OUTCOME_SET, {"outcome": "available" if can else "not_available"}),
                               (EventType.CONVERSATION_ENDED, {"reason": "ended"})]:
            await asyncio.sleep(0.05)
            self.bus.publish(job_id, type_, payload, conversation_id)

    async def hang_up(self, *, room):
        self.hung_up.append(room)
        conversation_id = room.removeprefix("call-")
        job_id = self.bus._db.get_conversation(conversation_id)["job_id"]
        self.bus.publish(job_id, EventType.CONVERSATION_ENDED, {"reason": "the person hung up"}, conversation_id)


def app_with(line: FakeLine) -> TestClient:
    settings = load_settings()
    settings.test_mode, settings.allowed_numbers, settings.demo_route_phone = True, [OWN], OWN
    app = create_app(settings=settings, database=Database(":memory:"), dialler=line)
    app.state.http = fake_google(FIVE)
    app.state.openai = FakeModel()
    app.state.sms = FakeSms()  # never the real Twilio in tests
    line.bus = app.state.bus
    return TestClient(app)


def wait_for(c: TestClient, job_id: str, predicate, seconds: float = 10) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        job = c.get(f"/jobs/{job_id}").json()
        if predicate(job):
            return job
        time.sleep(0.05)
    raise AssertionError(f"timed out; job is at {job['step']}")


def approved_job(c: TestClient) -> tuple[str, list[str]]:
    job_id = c.post("/jobs", json={**START, "request": "kitchen light flickers"}).json()["id"]
    ids = [p["id"] for p in wait_for(c, job_id, lambda j: j["step"] == "awaiting_approval")["people"]]
    c.post(f"/jobs/{job_id}/approve", json={"person_ids": ids[:2]})
    return job_id, ids


def test_approved_providers_are_called_in_order_and_each_gets_a_grounded_result() -> None:
    line = FakeLine()
    with app_with(line) as c:
        job_id, ids = approved_job(c)
        job = wait_for(c, job_id, lambda j: j["step"] == "awaiting_pick")
    assert line.dialled == [OWN, OWN]  # test mode: both calls ring the builder
    calls = job["conversations"]
    assert [conv["person_id"] for conv in calls] == ids[:2]  # best ranked first
    for conv in calls:
        assert conv["status"] == "ended" and conv["routed_to"] == OWN
        fact = conv["result"]["facts"][0]
        assert (conv["result"]["outcome"], fact["value"], fact["verified"]) == ("available", "500", True)
    # The record lets the agent give the full address if asked, and names the shop it calls.
    record = c.app.state.db.get_conversation(calls[0]["id"])["record"]
    assert record["shareable"]["address"] == START["address"]
    assert record["shareable"]["calling"] == job["people"][0]["name"]
    assert "wanted" not in record["shareable"]  # no preferred time from the user
    ready = [e for e in c.app.state.db.list_events(job_id) if e.type == "result_ready"]
    assert len(ready) == 2 and all(e.payload["routed"] for e in ready)


def test_skip_ends_the_call_in_progress_and_moves_on() -> None:
    line = FakeLine(hang={1})
    with app_with(line) as c:
        job_id, ids = approved_job(c)
        wait_for(c, job_id, lambda j: any(conv["status"] == "active" for conv in j["conversations"]))
        assert c.post(f"/jobs/{job_id}/skip").status_code == 200
        job = wait_for(c, job_id, lambda j: j["step"] == "awaiting_pick")
    assert len(line.hung_up) == 1 and len(line.dialled) == 2
    first, second = job["conversations"]
    assert first["result"]["outcome"] == "no_answer"  # the skipped call had nobody speaking
    assert second["result"]["outcome"] == "available"


def test_stop_calls_no_one_else() -> None:
    line = FakeLine(hang={1})
    with app_with(line) as c:
        job_id, _ = approved_job(c)
        wait_for(c, job_id, lambda j: any(conv["status"] == "active" for conv in j["conversations"]))
        assert c.post(f"/jobs/{job_id}/stop").status_code == 200
        c.post(f"/jobs/{job_id}/skip")
        job = wait_for(c, job_id, lambda j: j["step"] == "awaiting_pick")
    assert len(line.dialled) == 1 and len(job["conversations"]) == 1
    assert c.post(f"/jobs/{job_id}/stop").status_code == 409  # nothing running any more


def test_after_the_calls_a_recommendation_is_made_and_the_user_picks() -> None:
    line = FakeLine()
    with app_with(line) as c:
        job_id, ids = approved_job(c)
        job = wait_for(c, job_id, lambda j: j["step"] == "awaiting_pick")
        assert job["report"]["recommended_person_id"] == ids[0]
        assert job["report"]["reasoning"] == "Can come and charges 500 rupees to visit."  # grounded: 500 was said
        assert c.post(f"/jobs/{job_id}/pick", json={"person_id": ids[3]}).status_code == 422  # never called
        picked = c.post(f"/jobs/{job_id}/pick", json={"person_id": ids[1]}).json()  # not the recommended one
        assert picked["step"] == "confirming" and picked["report"]["picked_person_id"] == ids[1]
        assert c.post(f"/jobs/{job_id}/pick", json={"person_id": ids[0]}).status_code == 409
        wait_for(c, job_id, lambda j: j["step"] == "done")  # let the confirmation finish inside the test


def test_a_confirmed_booking_sends_only_the_address_and_is_done() -> None:
    line = FakeLine()
    with app_with(line) as c:
        job_id, ids = approved_job(c)
        wait_for(c, job_id, lambda j: j["step"] == "awaiting_pick")
        c.post(f"/jobs/{job_id}/pick", json={"person_id": ids[0]})
        job = wait_for(c, job_id, lambda j: j["step"] == "done")
        sms = c.app.state.sms.sent
    assert len(line.dialled) == 3  # two enquiries, then the confirmation call
    confirm = [conv for conv in job["conversations"] if conv["kind"] == "confirm_call"]
    assert len(confirm) == 1 and confirm[0]["person_id"] == ids[0]
    record = c.app.state.db.get_conversation(confirm[0]["id"])["record"]
    assert record["shareable"]["calling"] == job["people"][0]["name"]
    assert record["shareable"]["visiting_charge"] == "500 rupees"
    # One SMS, to the builder's phone in test mode, with the address and a map link only.
    map_link = f"https://maps.google.com/?q={START['lat']},{START['lng']}"
    assert sms == [{"to": OWN, "body": f"{START['address']}\n{map_link}"}]
    booking = job["report"]["booking"]
    assert booking["person_id"] == ids[0] and booking["sms_status"] == "sent" and booking["visiting_charge"] == "500"
    assert job["messages"][0]["routed_to"] == OWN


def test_a_failed_confirmation_goes_back_to_the_report_without_that_provider() -> None:
    line = FakeLine(refuse={3})  # the confirmation call: they cannot come any more
    with app_with(line) as c:
        job_id, ids = approved_job(c)
        wait_for(c, job_id, lambda j: j["step"] == "awaiting_pick")
        c.post(f"/jobs/{job_id}/pick", json={"person_id": ids[0]})
        job = wait_for(c, job_id, lambda j: j["step"] == "awaiting_pick" and "notice" in (j["report"] or {}))
        assert job["report"]["unavailable"] == [ids[0]] and "can't come any more" in job["report"]["notice"]
        assert c.app.state.sms.sent == []
        assert c.post(f"/jobs/{job_id}/pick", json={"person_id": ids[0]}).status_code == 422  # not again
        assert c.post(f"/jobs/{job_id}/pick", json={"person_id": ids[1]}).json()["step"] == "confirming"
        wait_for(c, job_id, lambda j: j["step"] == "done")


def test_an_english_job_calls_providers_in_telugu() -> None:
    from backend.jobs.calling import provider_record
    from backend.models import Person, PersonRole
    person = Person(id="per_1", job_id="job_1", role=PersonRole.PROVIDER, name="Sri Sai Electricals", source="test")
    job = {"start": {**START, "language": "en"}, "brief": {"service": "electrician", "work": "fan"}}
    assert provider_record(job, person, load_settings()).language.value == "te"
