"""Tests for the company side's screening calls and shortlist (docs/LLD.md, section 17).
Crawled candidates have no phone number, so their calls ring the builder whatever the test
mode; every score must rest on a quote from the transcript. The phone line, the worker and
the model are faked."""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.db import Database
from backend.main import create_app
from backend.models import EventType
from backend.settings import load_settings
from backend.tests.test_calling import FakeSms, wait_for
from backend.tests.test_roles import POSTING, PROFILES

OWN = "+919000000001"
INTERESTED_LINE = "Yes, I'm interested. I built an Airflow pipeline on AWS for two years. I expect 12 LPA."


class FakeModel:
    """The posting writer, the crawl, the call-result writer and the scorer."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.responses = SimpleNamespace(create=lambda **_: SimpleNamespace(output_text=json.dumps({"people": PROFILES})))
        self.records: list[str] = []

    def _create(self, **kwargs):
        name = kwargs["response_format"]["json_schema"]["name"]
        text = kwargs["messages"][-1]["content"]
        lines = [(int(m[1]), m[2]) for m in re.finditer(r"\[(\d+)\] PERSON: (.*)", text)]
        if name == "posting":
            answer = POSTING
        elif name == "call_result":
            self.records.append(text)
            seq, said = lines[0]
            if "interested" not in said or "not" in said:
                answer = {"outcome": "not_interested", "language_spoken": "en", "do_not_call": False, "notes": "",
                          "facts": []}
            else:
                answer = {"outcome": "interested", "language_spoken": "en", "do_not_call": False, "notes": "", "facts": [
                    {"name": "answer_1", "value": "Built an Airflow pipeline on AWS for two years.",
                     "said_as": "I built an Airflow pipeline on AWS for two years", "evidence_seq": seq},
                    {"name": "answer_2", "value": "Uses Python daily.", "said_as": "I built an Airflow pipeline",
                     "evidence_seq": seq},
                    {"name": "expected_salary", "value": "12 LPA", "said_as": "I expect 12 LPA", "evidence_seq": seq}]}
        else:  # the scorer: one grounded score, and one resting on words never said (dropped)
            seq, _ = lines[0]
            answer = {"summary": "Has relevant pipeline experience.", "scores": [
                {"question": 1, "score": 4, "quote": "I built an Airflow pipeline on AWS", "evidence_seq": seq,
                 "reason": "Concrete pipeline they built."},
                {"question": 2, "score": 5, "quote": "I am an expert in everything", "evidence_seq": seq,
                 "reason": "Invented."}]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer), tool_calls=None))])


class FakeLine:
    """The first candidate called is interested; the second is not."""

    def __init__(self):
        self.dialled: list[str] = []
        self.tasks: list = []
        self.bus = None

    async def dial(self, *, room, metadata, to):
        self.dialled.append(to)
        said = INTERESTED_LINE if len(self.dialled) == 1 else "Sorry, I'm not looking for a change right now."
        outcome = "interested" if len(self.dialled) == 1 else "not_interested"
        # Keep a reference: the event loop holds tasks only weakly.
        self.tasks.append(asyncio.get_running_loop().create_task(
            self._talk(metadata["job_id"], metadata["conversation_id"], said, outcome)))

    async def _talk(self, job_id, conversation_id, said, outcome):
        for type_, payload in [(EventType.AGENT_SAID, {"text": "Hello, am I speaking with the candidate?"}),
                               (EventType.PERSON_SAID, {"text": said}),
                               (EventType.OUTCOME_SET, {"outcome": outcome}),
                               (EventType.CONVERSATION_ENDED, {"reason": "ended"})]:
            await asyncio.sleep(0.05)
            self.bus.publish(job_id, type_, payload, conversation_id)

    async def hang_up(self, *, room):  # pragma: no cover - not used here
        pass


def app_with(line: FakeLine, model: FakeModel) -> TestClient:
    settings = load_settings()
    # Test mode off: the fallback must still ring the builder, never anyone else.
    settings.test_mode, settings.allowed_numbers, settings.demo_route_phone = False, [OWN], OWN
    app = create_app(settings=settings, database=Database(":memory:"), dialler=line)
    app.state.openai = model
    app.state.sms = FakeSms()
    line.bus = app.state.bus
    return TestClient(app)


def crawled_job(c: TestClient) -> dict:
    job_id = c.post("/roles", json={"company": "Acme Labs", "request": "Data engineer"}).json()["id"]
    p = wait_for(c, job_id, lambda j: j["step"] == "awaiting_posting")["posting"]
    c.post(f"/roles/{job_id}/posting/approve", json={k: p[k] for k in ("title", "job_description", "questions")})
    return wait_for(c, job_id, lambda j: j["step"] == "awaiting_approval")


def test_screening_calls_ring_the_builder_and_build_a_quoted_shortlist() -> None:
    line, model = FakeLine(), FakeModel()
    with app_with(line, model) as c:
        job = crawled_job(c)
        ids = [p["id"] for p in job["people"]]
        assert all(p["phone"] is None for p in job["people"])
        c.post(f"/jobs/{job['id']}/approve", json={"person_ids": ids})
        done = wait_for(c, job["id"], lambda j: j["step"] == "done")

    assert line.dialled == [OWN, OWN]  # nobody found on the web is ever rung
    calls = [x for x in done["conversations"] if x["kind"] == "screening_call"]
    assert len(calls) == 2 and all(x["routed_to"] == OWN for x in calls)
    record = c.app.state.db.get_conversation(calls[0]["id"])["record"]
    assert record["language"] == "en" and record["shareable"]["company"] == "Acme Labs"
    assert [f["name"] for f in record["facts_to_collect"]][-5:] == [f"answer_{i}" for i in range(1, 6)]
    assert "strong" not in json.dumps(record["shareable"])  # the scoring guide is never given to the agent

    first, second = done["report"]["shortlist"]
    assert first["name"] == "Asha Rao" and first["outcome"] == "interested" and first["rank"] == 1 and first["routed"]
    assert first["score"] == 4.0 and first["scored"] == 1 and first["asked"] == 2
    assert first["answers"][0]["score"] == 4 and first["answers"][0]["quote"] == "I built an Airflow pipeline on AWS"
    assert "score" not in first["answers"][1]  # its quote was never said, so the score is dropped
    assert any("question 2" in p for p in first["problems"])
    assert first["details"]["expected_salary"]["value"] == "12 LPA"
    assert second["outcome"] == "not_interested" and second["score"] is None and "rank" not in second


def test_at_most_the_call_cap_can_be_screened() -> None:
    from backend.models import Person, PersonRole
    c = app_with(FakeLine(), FakeModel())
    job = crawled_job(c)
    for i in range(2):
        c.app.state.db.add_person(Person(id=f"per_x{i}", job_id=job["id"], role=PersonRole.CANDIDATE,
                                         name=f"Extra {i}", source="web"))
    four = [p["id"] for p in job["people"]] + ["per_x0", "per_x1"]
    refused = c.post(f"/jobs/{job['id']}/approve", json={"person_ids": four})
    assert refused.status_code == 422 and "at most 3" in refused.json()["detail"]
