"""The confirming step (docs/LLD.md, section 7): call the provider the user picked,
confirm the visit at the time they offered, then send them the address by SMS.

If they confirm, one SMS goes to them with the address and a map link, nothing
else (builder's decision), and the job is done. If they cannot come any more, do
not answer, or the call is refused, the job goes back to the report with that
provider marked, so the user can pick another.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.calls import place_call
from backend.guardrails import local_now
from backend.jobs.calling import CallControl, controls, wait_for_end, write_result
from backend.jobs.steps import fail
from backend.messages import send_sms
from backend.models import ConversationRecord, EventType, JobStep, Language, Person
from backend.writers.comparison import spoken_time
from voice.engine.kinds import build_record

log = logging.getLogger(__name__)

OUTCOME_WORDS = {"not_available": "can't come any more", "no_answer": "didn't answer",
                 "declined": "declined", "wrong_number": "was a wrong number",
                 "call_customer": "wants to talk to you first"}


def first_call(state: Any, job_id: str, person_id: str) -> dict[str, Any] | None:
    return next((c for c in state.db.list_conversations(job_id, kind="home_call") if c["person_id"] == person_id), None)


def facts_of(conversation: dict[str, Any] | None) -> dict[str, str]:
    result = (conversation or {}).get("result") or {}
    return {f["name"]: f["value"] for f in result.get("facts", []) if f.get("verified") is not False}


def confirm_record(job: dict[str, Any], person: Person, first: dict[str, Any] | None, settings: Any) -> ConversationRecord:
    """What the agent may say when calling back: the shop, the job, the time and charge they offered."""
    start, brief = job["start"], job["brief"]
    facts = facts_of(first)
    result = (first or {}).get("result") or {}
    # Call back in the language they actually spoke on the first call.
    spoken = result.get("language_spoken") or (first or {}).get("language") or start["language"]
    language = Language(spoken) if spoken != Language.ENGLISH.value else Language.TELUGU
    now = local_now(settings).replace(tzinfo=None)
    shareable = {"calling": person.name, "work": brief["work"], "area": start["area"], "address": start["address"]}
    if facts.get("earliest_time"):
        shareable["offered_time"] = spoken_time(facts["earliest_time"], now)
    if facts.get("visiting_charge"):
        shareable["visiting_charge"] = f"{facts['visiting_charge']} rupees"
    return build_record("confirm_call", language, time_cap_seconds=settings.calling.time_cap_seconds,
                        wrap_up_at_seconds=settings.calling.wrap_up_at_seconds, shareable=shareable)


def address_message(job: dict[str, Any]) -> str:
    """The SMS: the address and a map link, nothing else."""
    start = job["start"]
    return f"{start['address']}\nhttps://maps.google.com/?q={start['lat']},{start['lng']}"


async def run_confirmation(state: Any, job_id: str) -> None:
    db, bus, settings = state.db, state.bus, state.settings
    control = controls(state).setdefault(job_id, CallControl())
    try:
        job = db.get_job(job_id)
        person = db.get_person(job["report"]["picked_person_id"])
        first = first_call(state, job_id, person.id)
        record = confirm_record(job, person, first, settings)
        conversation_id, refused = await place_call(db=db, bus=bus, settings=settings, dialler=state.dialler,
                                                    job_id=job_id, person=person, record=record)
        if refused:
            return back_to_pick(state, job_id, person, f"couldn't be called ({refused})")
        control.current = conversation_id
        await wait_for_end(state, job_id, conversation_id, control)
        control.current = None
        await asyncio.to_thread(write_result, state, job_id, conversation_id, person)

        result = db.get_conversation(conversation_id)["result"] or {}
        if result.get("outcome") != "available":
            return back_to_pick(state, job_id, person, OUTCOME_WORDS.get(result.get("outcome"), "couldn't confirm"))

        offered = facts_of(first)
        visit_time = facts_of(db.get_conversation(conversation_id)).get("visit_time") or offered.get("earliest_time")
        sms = await asyncio.to_thread(send_sms, state, job_id, person, address_message(job))
        report = db.get_job(job_id)["report"] or {}
        db.set_job_report(job_id, {**report, "booking": {
            "person_id": person.id, "visit_time": visit_time, "offered_time": offered.get("earliest_time"),
            "visiting_charge": offered.get("visiting_charge"), "address": job["start"]["address"],
            "conversation_id": conversation_id, "sms_status": sms["status"]}})
        db.set_job_step(job_id, JobStep.DONE)
        bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.DONE.value, "person_id": person.id})
    except Exception as exc:
        log.exception("confirmation failed for %s", job_id)
        fail(state, job_id, f"The confirmation stopped because of an error ({type(exc).__name__}).")
    finally:
        controls(state).pop(job_id, None)


def back_to_pick(state: Any, job_id: str, person: Person, why: str) -> None:
    """This provider could not be booked: back to the report, with them marked, so the
    user can pick someone else. The agent never books a different one by itself."""
    db, bus = state.db, state.bus
    report = dict(db.get_job(job_id)["report"] or {})
    report.pop("picked_person_id", None)
    report["unavailable"] = sorted({*report.get("unavailable", []), person.id})
    report["notice"] = f"{person.name} {why}."
    db.set_job_report(job_id, report)
    db.set_job_step(job_id, JobStep.AWAITING_PICK)
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.AWAITING_PICK.value, "notice": report["notice"]})
