"""Tests for the event bus and the event endpoints."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.db import Database
from backend.events import EventBus, format_sse
from backend.main import create_app
from backend.models import EventType, Side
from backend.settings import load_settings


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture
def bus(db: Database) -> EventBus:
    return EventBus(db)


def client_for(db: Database, token: str = "") -> TestClient:
    settings = load_settings()
    settings.secrets.internal_api_token = token
    return TestClient(create_app(settings=settings, database=db))


# --- the bus ----------------------------------------------------------------

def test_publish_stores_events_in_order(db: Database, bus: EventBus) -> None:
    job_id = db.create_job(Side.HOME)
    first = bus.publish(job_id, EventType.AGENT_SAID, {"text": "నమస్తే"})
    second = bus.publish(job_id, "person_said", {"text": "చెప్పండి"})
    assert (first.seq, second.seq) == (1, 2)
    assert [e.payload["text"] for e in db.list_events(job_id)] == ["నమస్తే", "చెప్పండి"]


def test_publish_rejects_unknown_types(db: Database, bus: EventBus) -> None:
    job_id = db.create_job(Side.HOME)
    with pytest.raises(ValueError):
        bus.publish(job_id, "made_up_type", {})
    assert db.list_events(job_id) == []


def test_stream_replays_then_follows_live(db: Database, bus: EventBus) -> None:
    job_id = db.create_job(Side.HOME)
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": "finding"})
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": "awaiting_approval"})

    async def scenario() -> list[int]:
        stream = bus.stream(job_id, after_seq=1, heartbeat_seconds=5)
        seen = [(await anext(stream)).seq]  # replay of seq 2 only
        # Published from another thread, as FastAPI's thread pool would.
        await asyncio.to_thread(bus.publish, job_id, EventType.AGENT_SAID, {"text": "live"})
        seen.append((await anext(stream)).seq)
        await stream.aclose()
        return seen

    assert asyncio.run(scenario()) == [2, 3]
    assert bus.subscriber_count == 0  # closing the stream unsubscribes


def test_stream_fills_a_gap_in_the_sequence(db: Database, bus: EventBus) -> None:
    job_id = db.create_job(Side.HOME)

    async def scenario() -> list[int]:
        stream = bus.stream(job_id, heartbeat_seconds=5)
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.05)  # let the stream subscribe
        # Stored without notifying, as if its notification were still in flight.
        db.add_event(job_id, EventType.AGENT_SAID, {"text": "first"})
        await asyncio.to_thread(bus.publish, job_id, EventType.PERSON_SAID, {"text": "second"})
        seen = [(await waiting).seq, (await anext(stream)).seq]
        await stream.aclose()
        return seen

    assert asyncio.run(scenario()) == [1, 2]


def test_stream_only_carries_its_own_job(db: Database, bus: EventBus) -> None:
    watched, other = db.create_job(Side.HOME), db.create_job(Side.HOME)

    async def scenario() -> list[str]:
        stream = bus.stream(watched, heartbeat_seconds=5)
        waiting = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.05)
        await asyncio.to_thread(bus.publish, other, EventType.AGENT_SAID, {"text": "not for you"})
        await asyncio.to_thread(bus.publish, watched, EventType.AGENT_SAID, {"text": "for you"})
        event = await waiting
        await stream.aclose()
        return [event.job_id, event.payload["text"]]

    assert asyncio.run(scenario()) == [watched, "for you"]


def test_stream_sends_heartbeats_when_idle(db: Database, bus: EventBus) -> None:
    job_id = db.create_job(Side.HOME)

    async def scenario() -> object:
        stream = bus.stream(job_id, heartbeat_seconds=0.05)
        beat = await anext(stream)
        await stream.aclose()
        return beat

    assert asyncio.run(scenario()) is None


def test_sse_format_carries_the_sequence_as_id(db: Database, bus: EventBus) -> None:
    job_id = db.create_job(Side.HOME)
    text = format_sse(bus.publish(job_id, EventType.AGENT_SAID, {"text": "హలో"}))
    assert text.startswith("id: 1\ndata: {")
    assert text.endswith("\n\n")
    assert "హలో" in text  # Indian scripts are sent as text, not escaped


# --- the endpoints ----------------------------------------------------------

def test_post_event_is_stored(db: Database) -> None:
    job_id = db.create_job(Side.HOME)
    response = client_for(db).post("/events", json={
        "job_id": job_id, "type": "person_said", "payload": {"text": "రేపు వస్తాను"}})
    assert response.status_code == 201
    assert response.json()["seq"] == 1
    assert db.list_events(job_id)[0].payload == {"text": "రేపు వస్తాను"}


def test_post_event_rejects_unknown_job_and_type(db: Database) -> None:
    client = client_for(db)
    assert client.post("/events", json={"job_id": "job_missing", "type": "agent_said"}).status_code == 404
    job_id = db.create_job(Side.HOME)
    assert client.post("/events", json={"job_id": job_id, "type": "made_up_type"}).status_code == 422


def test_post_event_rejects_a_conversation_from_another_job(db: Database) -> None:
    job_id, other = db.create_job(Side.HOME), db.create_job(Side.HOME)
    conversation_id = db.create_conversation(other, "home_call", "te", {})
    response = client_for(db).post("/events", json={
        "job_id": job_id, "conversation_id": conversation_id, "type": "agent_said"})
    assert response.status_code == 404


def test_post_event_checks_the_token_when_one_is_set(db: Database) -> None:
    job_id = db.create_job(Side.HOME)
    client = client_for(db, token="s3cret")
    body = {"job_id": job_id, "type": "agent_said"}
    assert client.post("/events", json=body).status_code == 401
    assert client.post("/events", json=body, headers={"X-Internal-Token": "wrong"}).status_code == 401
    assert client.post("/events", json=body, headers={"X-Internal-Token": "s3cret"}).status_code == 201


def test_the_worker_can_fetch_its_conversation_record(db: Database) -> None:
    job_id = db.create_job(Side.HOME)
    conversation_id = db.create_conversation(job_id, "home_call", "te", {"kind": "home_call", "goal": "g"})
    client = client_for(db, token="s3cret")
    assert client.get(f"/conversations/{conversation_id}").status_code == 401
    response = client.get(f"/conversations/{conversation_id}", headers={"X-Internal-Token": "s3cret"})
    assert response.status_code == 200 and response.json()["record"]["goal"] == "g"
    assert client.get("/conversations/conv_missing", headers={"X-Internal-Token": "s3cret"}).status_code == 404


def test_stream_of_unknown_job_is_404(db: Database) -> None:
    assert client_for(db).get("/events/stream", params={"job_id": "job_missing"}).status_code == 404
