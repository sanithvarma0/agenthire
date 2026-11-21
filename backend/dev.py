"""Development endpoints. Available only in test mode, so they can only ever
reach the builder's own numbers (can_dial refuses every other number in test mode)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.calls import place_call
from backend.db import new_id
from backend.models import Language, Person, PersonRole, Side
from voice.engine.kinds import build_record

router = APIRouter(prefix="/dev")


class TestCall(BaseModel):
    to: str
    language: Language = Language.TELUGU
    calling: str  # the business or person the agent asks for when the call is picked up
    work: str
    area: str
    when: str = "tomorrow"


@router.post("/test-call")
async def test_call(body: TestCall, request: Request) -> dict:
    """Create a job with one approved person and call them, through the real guardrails."""
    state = request.app.state
    settings = state.settings
    if not settings.test_mode:
        raise HTTPException(status_code=403, detail="development calls need test mode")

    db = state.db
    job_id = db.create_job(Side.HOME)
    person = Person(id=new_id("per"), job_id=job_id, role=PersonRole.PROVIDER, name=body.calling,
                    phone=body.to, source="test")
    db.add_person(person)
    db.approve_people(job_id, [person.id])
    record = build_record("home_call", body.language,
                          time_cap_seconds=settings.calling.time_cap_seconds,
                          wrap_up_at_seconds=settings.calling.wrap_up_at_seconds,
                          shareable={"calling": body.calling, "work": body.work, "area": body.area,
                                     "wanted": body.when})
    conversation_id, refused = await place_call(db=db, bus=state.bus, settings=settings, dialler=state.dialler,
                                                job_id=job_id, person=person, record=record)
    return {"job_id": job_id, "conversation_id": conversation_id, "refused": refused}
