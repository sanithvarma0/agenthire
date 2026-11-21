"""The calling step (docs/LLD.md, section 7): phone the approved providers one at a
time, best ranked first, and write each call's result as soon as it ends.

Each call goes through `place_call`, so every guardrail applies. The voice worker
holds the conversation and reports `conversation_ended` when the call is over
(answered and finished, not answered, hung up, or its room closed). This step
waits for that, then writes the result from the whole transcript with the larger
model and checks every fact against the line it cites. The user can skip the call
in progress (its room is closed) or stop after it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from backend.calls import place_call, room_name
from backend.guardrails import ground_call_result, local_now
from backend.jobs import reporting
from backend.jobs.steps import fail, openai_client
from backend.models import CallResult, ConversationRecord, EventType, JobStep, Language, Outcome, Person
from backend.writers.call_result import transcript_from_events, write_call_result
from voice.engine.kinds import build_record

log = logging.getLogger(__name__)

POLL_SECONDS = 0.5
RING_SECONDS = 60           # time allowed for the phone to be answered
REPORT_GRACE_SECONDS = 60   # beyond the time cap, before a silent call is given up on
SKIP_GRACE_SECONDS = 8      # after closing a skipped call's room, wait this long for the worker's report


@dataclass
class CallControl:
    """The user's controls for one job's calls."""
    current: str | None = None     # the conversation in progress
    skip: bool = False             # end the call in progress and go to the next
    stop: bool = False             # call no one else after the call in progress


def controls(state: Any) -> dict[str, CallControl]:
    if getattr(state, "call_controls", None) is None:
        state.call_controls = {}
    return state.call_controls


def provider_record(job: dict[str, Any], person: Person, settings: Any) -> ConversationRecord:
    """What the agent may say on a first call to this provider."""
    start, brief = job["start"], job["brief"]
    language = Language(start["language"])
    if language == Language.ENGLISH:
        language = Language.TELUGU  # most local tradespeople speak Telugu or Hindi; the call follows them
    return build_record(
        "home_call", language,
        time_cap_seconds=settings.calling.time_cap_seconds, wrap_up_at_seconds=settings.calling.wrap_up_at_seconds,
        shareable={"calling": person.name, "work": brief["work"], "area": start["area"],
                   "address": start["address"]},
    )


async def run_calls(state: Any, job_id: str) -> None:
    """Call each approved provider in rank order, then move the job on to reporting."""
    db, bus, settings = state.db, state.bus, state.settings
    control = controls(state).setdefault(job_id, CallControl())
    try:
        job = db.get_job(job_id)
        for person in db.list_people(job_id, approved_only=True):  # stored best first
            if control.stop:
                break
            record = provider_record(job, person, settings)
            conversation_id, refused = await place_call(db=db, bus=bus, settings=settings, dialler=state.dialler,
                                                        job_id=job_id, person=person, record=record)
            if refused:
                continue  # shown on screen from its guardrail_blocked event
            control.current, control.skip = conversation_id, False
            await wait_for_end(state, job_id, conversation_id, control)
            control.current = None
            await asyncio.to_thread(write_result, state, job_id, conversation_id, person)
        db.set_job_step(job_id, JobStep.REPORTING)
        bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.REPORTING.value, "stopped": control.stop})
        await asyncio.to_thread(reporting.report, state, job_id)
    except Exception as exc:
        log.exception("calling failed for %s", job_id)
        fail(state, job_id, f"The calls stopped because of an error ({type(exc).__name__}).")
    finally:
        controls(state).pop(job_id, None)


def _ended(state: Any, job_id: str, conversation_id: str) -> bool:
    return any(e.type == EventType.CONVERSATION_ENDED.value
               for e in state.db.list_events(job_id, conversation_id=conversation_id))


async def wait_for_end(state: Any, job_id: str, conversation_id: str, control: CallControl) -> None:
    """Until the worker reports the call over. A skip closes the room; a call that never
    reports is ended here, so the job cannot hang."""
    settings = state.settings
    limit = RING_SECONDS + settings.calling.time_cap_seconds + REPORT_GRACE_SECONDS
    waited, skip_deadline = 0.0, None
    while not _ended(state, job_id, conversation_id):
        if control.skip and skip_deadline is None:
            skip_deadline = waited + SKIP_GRACE_SECONDS
            try:
                await state.dialler.hang_up(room=room_name(conversation_id))
            except Exception as exc:
                log.warning("Could not close the room of %s: %s", conversation_id, exc)
        if waited >= limit or (skip_deadline is not None and waited >= skip_deadline):
            reason = "skipped by the user" if control.skip else "no report from the call"
            state.bus.publish(job_id, EventType.CONVERSATION_ENDED, {"reason": reason}, conversation_id)
            break
        await asyncio.sleep(POLL_SECONDS)
        waited += POLL_SECONDS


def write_result(state: Any, job_id: str, conversation_id: str, person: Person) -> None:
    """The result the user sees: written from the whole transcript, then grounded."""
    db, bus, settings = state.db, state.bus, state.settings
    events = db.list_events(job_id, conversation_id=conversation_id)
    transcript = transcript_from_events(events)
    record = ConversationRecord(**db.get_conversation(conversation_id)["record"])
    live = _live_result(events)
    problems: list[str] = []
    try:
        result = write_call_result(record, transcript, client=openai_client(state), settings=settings,
                                   now=local_now(settings).replace(tzinfo=None), live=live)
        result, problems = ground_call_result(result, transcript)
    except Exception as exc:  # a model failure must not lose the call: keep what was recorded live
        log.exception("result writer failed for %s", conversation_id)
        result = live or CallResult(outcome=Outcome.NO_ANSWER)
        problems = [f"result written from the live notes only ({type(exc).__name__})"]
    data = result.model_dump(mode="json")
    db.set_conversation_result(conversation_id, data)
    db.set_conversation_status(conversation_id, "ended")
    routed = bool(db.get_conversation(conversation_id).get("routed_to"))
    bus.publish(job_id, EventType.RESULT_READY, {"person_id": person.id, "result": data, "problems": problems,
                                                 "routed": routed}, conversation_id)


def _live_result(events: list) -> CallResult | None:
    """What the agent recorded during the call: its outcome and a do-not-call, if any."""
    outcome, do_not_call = None, False
    for e in events:
        if e.type == EventType.OUTCOME_SET.value:
            outcome = e.payload.get("outcome")
        elif e.type == EventType.TOOL_CALLED.value and e.payload.get("name") == "mark_do_not_call":
            do_not_call = True
    if outcome is None and not do_not_call:
        return None
    return CallResult(outcome=Outcome(outcome or Outcome.DECLINED.value), do_not_call=do_not_call)
