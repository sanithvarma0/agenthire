"""The voice brief (docs/LLD.md, section 7): a live conversation in the browser.

`POST /jobs` without a typed request opens a LiveKit room for the `brief` kind in the
user's chosen language and sends the voice worker into it; the web app joins with a
token from `POST /jobs/{id}/voice`. When the conversation ends (the user confirmed the
summary), the brief writer reads the whole transcript and the finding step runs, as
for a typed request.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.db import new_id
from backend.jobs.calling import CallControl, controls, wait_for_end
from backend.jobs.steps import fail, find, write_role
from backend.models import EventType, Language
from voice.engine.kinds import build_record

log = logging.getLogger(__name__)

BRIEF_KIND = "brief"  # home side: what needs fixing
ROLE_BRIEF_KIND = "role_brief"  # company side: the role being hired for
BRIEF_KINDS = (BRIEF_KIND, ROLE_BRIEF_KIND)


def room_for(conversation_id: str) -> str:
    return f"brief-{conversation_id}"


async def open_brief(state: Any, job_id: str) -> str:
    """Record the brief conversation and open its room. Returns the conversation id.
    A home job gets the `brief` kind in the user's language with the area; a company job
    gets `role_brief` in English with the company's name."""
    db, settings = state.db, state.settings
    job = db.get_job(job_id)
    start = job["start"]
    if job["side"] == "company":
        kind, language, shareable = ROLE_BRIEF_KIND, Language.ENGLISH, {"company": start["company"]}
    else:
        kind, language, shareable = BRIEF_KIND, Language(start["language"]), {"area": start["area"]}
    record = build_record(kind, language, time_cap_seconds=settings.calling.time_cap_seconds,
                          wrap_up_at_seconds=settings.calling.wrap_up_at_seconds, shareable=shareable)
    conversation_id = db.create_conversation(job_id, kind, record.language.value, record.model_dump(mode="json"))
    db.set_conversation_status(conversation_id, "active")
    await state.dialler.open_room(room=room_for(conversation_id),
                                  metadata={"conversation_id": conversation_id, "job_id": job_id})
    return conversation_id


def brief_conversation(state: Any, job_id: str) -> dict[str, Any] | None:
    found = [c for c in state.db.list_conversations(job_id) if c["kind"] in BRIEF_KINDS]
    return found[-1] if found else None


def voice_access(state: Any, job_id: str) -> dict[str, str]:
    """What the web app needs to join the brief's room."""
    conversation = brief_conversation(state, job_id)
    if conversation is None or conversation["status"] != "active":
        raise LookupError("no voice brief is open for this job")
    room = room_for(conversation["id"])
    token = state.dialler.browser_token(room=room, identity=f"user-{new_id('u')}")
    return {"url": state.settings.secrets.livekit_url, "token": token, "room": room,
            "conversation_id": conversation["id"]}


async def run_brief(state: Any, job_id: str, conversation_id: str) -> None:
    """Wait for the brief to end, then go on: a home job understands it and finds
    providers; a company job writes the posting from it."""
    db = state.db
    company = db.get_job(job_id)["side"] == "company"
    then = write_role if company else find
    nothing = ("Didn't hear anything. Start again and describe the role." if company
               else "Didn't hear anything. Start again and tell me what needs fixing.")
    control = controls(state).setdefault(job_id, CallControl())
    try:
        control.current = conversation_id
        await wait_for_end(state, job_id, conversation_id, control)
        control.current = None
        db.set_conversation_status(conversation_id, "ended")
        lines = [(e.type, str(e.payload.get("text", "")))
                 for e in db.list_events(job_id, conversation_id=conversation_id)
                 if e.type in (EventType.AGENT_SAID.value, EventType.PERSON_SAID.value)]
        if not any(kind == EventType.PERSON_SAID.value for kind, _ in lines):
            return fail(state, job_id, nothing)
        said = "\n".join(f"{'USER' if kind == EventType.PERSON_SAID.value else 'AGENT'}: {text}" for kind, text in lines)
        await asyncio.to_thread(then, state, job_id, said)
    except Exception as exc:
        log.exception("voice brief failed for %s", job_id)
        fail(state, job_id, f"The voice brief stopped because of an error ({type(exc).__name__}).")
    finally:
        controls(state).pop(job_id, None)
