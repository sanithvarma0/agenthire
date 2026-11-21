"""The event stream: every sentence, tool call and state change of a job, in order.

`EventBus.publish` stores an event and hands it to everyone watching that job.
`EventBus.stream` replays what is already stored, then follows new events live.
The web app's live transcript is built from this stream (docs/HLD.md, section 4).
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.db import Database
from backend.models import Event, EventType

HEARTBEAT_SECONDS = 15


class EventBus:
    """Stores events and fans them out to live subscribers.

    `publish` may be called from any thread (FastAPI runs plain endpoints in a
    thread pool); each subscriber is woken on its own event loop.
    """

    def __init__(self, db: Database):
        self._db = db
        self._lock = threading.Lock()
        self._ids = itertools.count()
        self._subscribers: dict[int, tuple[str, asyncio.AbstractEventLoop, asyncio.Queue[Event]]] = {}

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, job_id: str, type: EventType | str, payload: dict[str, Any] | None = None,
                conversation_id: str | None = None) -> Event:
        """Store an event, then notify subscribers of that job. Unknown types raise ValueError."""
        event = self._db.add_event(job_id, EventType(type), payload or {}, conversation_id)
        with self._lock:
            targets = [(loop, queue) for job, loop, queue in self._subscribers.values() if job == job_id]
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # that subscriber's loop has already closed
                pass
        return event

    async def stream(self, job_id: str, after_seq: int = 0,
                     heartbeat_seconds: float = HEARTBEAT_SECONDS) -> AsyncIterator[Event | None]:
        """Yield a job's events after `after_seq`, in order, forever.

        Yields None when nothing has happened for `heartbeat_seconds`, so the
        caller can keep the connection open. Subscribes before replaying, so no
        event is lost between the replay and the live part; any gap in the
        sequence (two publishes racing) is filled from the database.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue()
        key = next(self._ids)
        with self._lock:
            self._subscribers[key] = (job_id, asyncio.get_running_loop(), queue)
        last = after_seq
        try:
            for event in self._db.list_events(job_id, after_seq=last):
                yield event
                last = event.seq
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                except TimeoutError:
                    yield None
                    continue
                if event.seq <= last:
                    continue  # already sent during the replay or a gap fill
                for missed in self._db.list_events(job_id, after_seq=last):
                    if missed.seq > event.seq:
                        break
                    yield missed
                    last = missed.seq
        finally:
            with self._lock:
                self._subscribers.pop(key, None)


def format_sse(event: Event) -> str:
    """One server-sent event. The id is the job's sequence number, so a browser
    that reconnects sends it back as Last-Event-ID and misses nothing."""
    return f"id: {event.seq}\ndata: {event.model_dump_json()}\n\n"


# --- HTTP endpoints ---------------------------------------------------------

router = APIRouter()


class EventIn(BaseModel):
    """An event reported by the voice worker."""

    job_id: str
    conversation_id: str | None = None
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


def _check_token(request: Request, token: str | None) -> None:
    from backend.conversations import check_internal_token

    check_internal_token(request, token)


@router.post("/events", status_code=201)
def post_event(body: EventIn, request: Request,
               x_internal_token: str | None = Header(default=None)) -> Event:
    _check_token(request, x_internal_token)
    db: Database = request.app.state.db
    if db.get_job(body.job_id) is None:
        raise HTTPException(status_code=404, detail="no such job")
    if body.conversation_id is not None:
        conversation = db.get_conversation(body.conversation_id)
        if conversation is None or conversation["job_id"] != body.job_id:
            raise HTTPException(status_code=404, detail="no such conversation in this job")
    return request.app.state.bus.publish(body.job_id, body.type, body.payload, body.conversation_id)


@router.get("/events/stream")
async def event_stream(request: Request, job_id: str, after: int | None = None,
                       last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    """Server-sent events for one job. Resumes after `after`, or after the
    Last-Event-ID header a reconnecting browser sends."""
    if request.app.state.db.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="no such job")
    if after is None:
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    bus: EventBus = request.app.state.bus

    async def body() -> AsyncIterator[str]:
        yield "retry: 2000\n\n"
        async for event in bus.stream(job_id, after_seq=after):
            yield ": keep-alive\n\n" if event is None else format_sse(event)

    return StreamingResponse(
        body(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
