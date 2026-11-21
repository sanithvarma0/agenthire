"""The voice brief end to end with a fake worker: the room opens, the conversation is
held, and when it ends the transcript is understood and providers are found."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.db import Database
from backend.main import create_app
from backend.models import EventType
from backend.settings import load_settings
from backend.tests.test_jobs import FIVE, START, NoDialler, fake_google


class FakeModel:
    def __init__(self):
        self.asked: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.asked.append(kwargs["messages"][-1]["content"])
        answer = {"service": "electrician", "work": "Kitchen light flickers.", "understood": True}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])


def app_with(model: FakeModel) -> TestClient:
    app = create_app(settings=load_settings(), database=Database(":memory:"), dialler=NoDialler())
    app.state.http, app.state.openai = fake_google(FIVE), model
    return TestClient(app)


def wait_for(c: TestClient, job_id: str, predicate, seconds: float = 10) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        job = c.get(f"/jobs/{job_id}").json()
        if predicate(job):
            return job
        time.sleep(0.05)
    raise AssertionError(f"timed out at {job['step']}")


def test_the_brief_transcript_is_understood_and_providers_are_found() -> None:
    model = FakeModel()
    with app_with(model) as c:
        job = c.post("/jobs", json=START).json()
        conversation_id = job["conversations"][0]["id"]
        bus = c.app.state.bus
        for type_, text in [(EventType.AGENT_SAID, "నమస్తే అండి, ఇంట్లో ఏం fix చేయించాలి?"),
                            (EventType.PERSON_SAID, "kitchen లో light flicker అవుతుంది"),
                            (EventType.AGENT_SAID, "kitchen light flicker అవుతోంది, ఇదేనా?"),
                            (EventType.PERSON_SAID, "అవును")]:
            bus.publish(job["id"], type_, {"text": text}, conversation_id)
        bus.publish(job["id"], EventType.CONVERSATION_ENDED, {"reason": "confirmed"}, conversation_id)
        done = wait_for(c, job["id"], lambda j: j["step"] == "awaiting_approval")
    assert done["brief"]["service"] == "electrician" and len(done["people"]) == 5
    # The writer read the whole conversation, the user's lines marked as theirs.
    assert "USER: kitchen లో light flicker అవుతుంది" in model.asked[0] and "AGENT:" in model.asked[0]
    assert c.app.state.db.get_conversation(conversation_id)["status"] == "ended"


def test_a_brief_where_the_user_said_nothing_is_reported() -> None:
    with app_with(FakeModel()) as c:
        job = c.post("/jobs", json=START).json()
        conversation_id = job["conversations"][0]["id"]
        c.app.state.bus.publish(job["id"], EventType.CONVERSATION_ENDED, {"reason": "call closed"}, conversation_id)
        done = wait_for(c, job["id"], lambda j: j["status"] == "failed")
        assert "Didn't hear anything" in done["error"]
        assert c.post(f"/jobs/{job['id']}/voice").status_code == 409  # the room is closed
