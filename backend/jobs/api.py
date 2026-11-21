"""Job endpoints for the web app (docs/LLD.md, section 8).

The web app follows the job's step from `GET /jobs/{id}` and its event stream, so a
reload or another device lands on the same screen. Slow steps (understanding the
request, searching) run after the response, and announce themselves on the stream.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.jobs import briefing, calling, confirming, steps
from backend.models import EventType, JobStart, JobStep, Side

router = APIRouter(prefix="/jobs")

RECENT_JOBS = 10
MAX_JOBS_LISTED = 100


def job_view(request: Request, job_id: str) -> dict[str, Any]:
    """Everything the web app shows for one job."""
    state = request.app.state
    job = state.db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    conversations = [
        {k: c.get(k) for k in ("id", "person_id", "kind", "language", "status", "started_at", "ended_at",
                               "result", "routed_to")}
        for c in state.db.list_conversations(job_id)
    ]
    return {
        "id": job["id"], "side": job["side"], "step": job["step"], "status": job["status"],
        "error": job.get("error"), "start": job["start"], "brief": job["brief"], "search": job.get("search"),
        "report": job.get("report"), "posting": job.get("posting"),
        "created_at": job["created_at"], "updated_at": job["updated_at"],
        "people": state.db.people_view(job_id),
        "conversations": conversations,
        "messages": state.db.list_messages(job_id),
        # The web app shows a banner when calls ring the builder's phone.
        "test_mode": state.settings.test_mode,
    }


@router.post("")
async def start_job(body: JobStart, request: Request, background: BackgroundTasks) -> dict[str, Any]:
    """Start a home-side job from the Start screen: language, address and location.
    A typed request goes straight on to understanding it and finding providers; without
    one, a voice brief opens in the browser (join it with POST /jobs/{id}/voice)."""
    state = request.app.state
    job_id = state.db.create_job(Side.HOME, start=body.model_dump(mode="json"))
    state.bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.BRIEFING.value})
    if body.request:
        background.add_task(steps.find, state, job_id)
    else:
        try:
            conversation_id = await briefing.open_brief(state, job_id)
        except Exception as exc:
            steps.fail(state, job_id, f"Couldn't open the voice brief ({type(exc).__name__}). Type it instead.")
        else:
            run_in_background(state, job_id, briefing.run_brief(state, job_id, conversation_id))
    return job_view(request, job_id)


@router.post("/{job_id}/voice")
def voice(job_id: str, request: Request) -> dict[str, str]:
    """A token for the web app to join this job's voice brief (again after a reload)."""
    job_view(request, job_id)
    try:
        return briefing.voice_access(request.app.state, job_id)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class Approval(BaseModel):
    person_ids: list[str] = Field(min_length=1)


@router.post("/{job_id}/approve")
async def approve(job_id: str, body: Approval, request: Request) -> dict[str, Any]:
    """The providers the user chose to have called: the top ranked, or their swap.
    Nothing is dialled without this (can_dial checks the approval). The calls then
    run one after another in the background."""
    state = request.app.state
    job = job_view(request, job_id)
    if job["step"] != JobStep.AWAITING_APPROVAL.value:
        raise HTTPException(status_code=409, detail=f"the job is at {job['step']}, not waiting for approval")
    call_top = state.settings.providers.call_top
    ids = list(dict.fromkeys(body.person_ids))
    if len(ids) > call_top:
        raise HTTPException(status_code=422, detail=f"choose at most {call_top}")
    known = {p["id"] for p in job["people"]}
    if unknown := [i for i in ids if i not in known]:
        raise HTTPException(status_code=422, detail=f"not found for this job: {', '.join(unknown)}")
    if job["side"] == Side.COMPANY.value:
        # Crawled candidates have no phone number; their screening calls ring the builder
        # (docs/LLD.md, section 17). Built in task 4.6.
        raise HTTPException(status_code=409, detail="screening calls are not built yet")
    state.db.approve_people(job_id, ids)
    state.db.set_job_step(job_id, JobStep.CALLING)
    state.bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.CALLING.value, "approved": ids})
    start_calls(state, job_id)
    return job_view(request, job_id)


def start_calls(state: Any, job_id: str) -> None:
    run_in_background(state, job_id, calling.run_calls(state, job_id))


def run_in_background(state: Any, job_id: str, step: Any) -> None:
    """Run a calling step on the server's event loop, keeping a reference so it is not lost."""
    if getattr(state, "tasks", None) is None:
        state.tasks = set()
    calling.controls(state)[job_id] = calling.CallControl()  # Skip and Stop work from the first moment
    task = asyncio.get_running_loop().create_task(step)
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)


def _call_control(request: Request, job_id: str) -> calling.CallControl:
    control = calling.controls(request.app.state).get(job_id)
    if control is None:
        raise HTTPException(status_code=409, detail="no calls are running for this job")
    return control


@router.post("/{job_id}/skip")
def skip(job_id: str, request: Request) -> dict[str, Any]:
    """End the call in progress and move on to the next provider."""
    control = _call_control(request, job_id)
    if control.current is None:
        raise HTTPException(status_code=409, detail="no call is in progress")
    control.skip = True
    return {"skipping": control.current}


@router.post("/{job_id}/stop")
def stop(job_id: str, request: Request) -> dict[str, Any]:
    """Call no one else after the call in progress; then the report is built from what was found."""
    control = _call_control(request, job_id)
    control.stop = True
    request.app.state.bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.CALLING.value, "stopping": True})
    return {"stopping": True}


class Pick(BaseModel):
    person_id: str


@router.post("/{job_id}/pick")
async def pick(job_id: str, body: Pick, request: Request) -> dict[str, Any]:
    """The provider the user chose from the report: only one who said they can come and
    has not already failed to confirm. The confirmation call then runs in the background."""
    state = request.app.state
    job = job_view(request, job_id)
    if job["step"] != JobStep.AWAITING_PICK.value:
        raise HTTPException(status_code=409, detail=f"the job is at {job['step']}, not waiting for a pick")
    able = {c["person_id"] for c in job["conversations"]
            if c["kind"] == "home_call" and (c["result"] or {}).get("outcome") == "available"}
    able -= set((job["report"] or {}).get("unavailable", []))
    if body.person_id not in able:
        raise HTTPException(status_code=422, detail="pick one of the providers who can come")
    report = {k: v for k, v in (job["report"] or {}).items() if k != "notice"}
    state.db.set_job_report(job_id, {**report, "picked_person_id": body.person_id})
    state.db.set_job_step(job_id, JobStep.CONFIRMING)
    state.bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.CONFIRMING.value, "picked": body.person_id})
    run_in_background(state, job_id, confirming.run_confirmation(state, job_id))
    return job_view(request, job_id)


@router.get("")
def recent_jobs(request: Request, limit: int = Query(RECENT_JOBS, ge=1, le=MAX_JOBS_LISTED)) -> list[dict[str, Any]]:
    """The latest jobs started from the web app, newest first, for the Start screen (a few)
    and History (more, with how each ended). Jobs made by development test calls have no
    start and are left out."""
    db = request.app.state.db
    jobs = [j for j in db.list_jobs() if j["start"]][:limit]
    return [job_summary(db, j) for j in jobs]


def job_summary(db: Any, job: dict[str, Any]) -> dict[str, Any]:
    """One line of History: what was asked, how far it got, and the booking if there was one."""
    calls = db.list_conversations(job["id"], kind="home_call")
    booking = (job.get("report") or {}).get("booking")
    booked = None
    if booking:
        person = db.get_person(booking["person_id"])
        booked = {"name": person.name if person else None, "visit_time": booking.get("visit_time"),
                  "visiting_charge": booking.get("visiting_charge")}
    return {
        "id": job["id"], "side": job["side"], "step": job["step"], "status": job["status"],
        "created_at": job["created_at"], "company": job["start"].get("company"),
        "brief": job["brief"], "request": job["start"].get("request"), "area": job["start"].get("area"),
        "language": job["start"].get("language"), "error": job.get("error"),
        "found": len(db.list_people(job["id"])), "called": len(calls),
        "available": sum(1 for c in calls if (c.get("result") or {}).get("outcome") == "available"),
        "booked": booked,
    }


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    return job_view(request, job_id)
