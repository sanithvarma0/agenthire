"""The test-mode switch: locked without a PIN, needs the right PIN, never mid-call, and only
changes the running back end (a new app starts in test mode again)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.db import Database
from backend.main import create_app
from backend.models import JobStep, Side
from backend.settings import load_settings


def client(pin: str = "") -> TestClient:
    settings = load_settings()
    settings.test_mode, settings.test_mode_pin = True, pin
    return TestClient(create_app(settings=settings, database=Database(":memory:"), dialler=object()))


def test_without_a_pin_the_switch_is_locked() -> None:
    c = client()
    assert c.get("/mode").json() == {"test_mode": True, "switchable": False}
    assert c.post("/mode", json={"test_mode": False, "pin": ""}).status_code == 403
    assert c.get("/mode").json()["test_mode"] is True


def test_the_right_pin_switches_it_off_and_on() -> None:
    c = client(pin="2468")
    assert c.post("/mode", json={"test_mode": False, "pin": "1111"}).status_code == 403
    assert c.post("/mode", json={"test_mode": False, "pin": "2468"}).json() == {"test_mode": False, "switchable": True}
    assert c.app.state.settings.test_mode is False  # what the guardrails read
    assert c.post("/mode", json={"test_mode": True, "pin": "2468"}).json()["test_mode"] is True


def test_it_does_not_switch_while_a_job_is_calling() -> None:
    c = client(pin="2468")
    db = c.app.state.db
    job = db.create_job(Side.HOME, {"language": "te"})
    db.set_job_step(job, JobStep.CALLING)
    assert c.post("/mode", json={"test_mode": False, "pin": "2468"}).status_code == 409
    assert c.app.state.settings.test_mode is True
