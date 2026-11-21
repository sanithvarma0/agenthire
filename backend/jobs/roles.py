"""Company-side endpoints (docs/LLD.md, section 17). A company job is an ordinary job with
`side = company`: the web app follows it with `GET /jobs/{id}` and its event stream, joins
its voice brief with `POST /jobs/{id}/voice`, and approves calls with `POST /jobs/{id}/approve`.
These endpoints cover what only the company side has: starting from a role, and editing
and approving the posting.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from backend.db import now
from backend.jobs import briefing, steps
from backend.jobs.api import job_view, run_in_background
from backend.models import EventType, JobStep, Language, Posting, RoleStart, ScreeningQuestion, Side

router = APIRouter(prefix="/roles")


@router.post("")
async def start_role(body: RoleStart, request: Request, background: BackgroundTasks) -> dict[str, Any]:
    """Start a company job: the company's name and, if typed, the role. Without a typed
    role, a role brief opens in the browser (join it with POST /jobs/{id}/voice)."""
    state = request.app.state
    start = {"company": body.company.strip(), "language": Language.ENGLISH.value,
             "request": body.request.strip() if body.request else None}
    job_id = state.db.create_job(Side.COMPANY, start=start)
    state.bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.BRIEFING.value})
    if start["request"]:
        background.add_task(steps.write_role, state, job_id)
    else:
        try:
            conversation_id = await briefing.open_brief(state, job_id)
        except Exception as exc:
            steps.fail(state, job_id, f"Couldn't open the voice brief ({type(exc).__name__}). Type the role instead.")
        else:
            run_in_background(state, job_id, briefing.run_brief(state, job_id, conversation_id))
    return job_view(request, job_id)


class PostingEdit(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    job_description: str = Field(min_length=20, max_length=6000)
    questions: list[ScreeningQuestion] = Field(min_length=1, max_length=5)


def _awaiting_posting(request: Request, job_id: str) -> dict[str, Any]:
    job = job_view(request, job_id)
    if job["side"] != Side.COMPANY.value:
        raise HTTPException(status_code=404, detail="not a company job")
    if job["step"] != JobStep.AWAITING_POSTING.value:
        raise HTTPException(status_code=409, detail=f"the job is at {job['step']}, not waiting for the posting")
    return job


@router.put("/{job_id}/posting")
def save_posting(job_id: str, body: PostingEdit, request: Request) -> dict[str, Any]:
    """HR's edits to the job description, the questions or the scoring guide."""
    _awaiting_posting(request, job_id)
    request.app.state.db.set_job_posting(job_id, Posting(**body.model_dump()).model_dump())
    return job_view(request, job_id)


@router.post("/{job_id}/posting/approve")
def approve_posting(job_id: str, body: PostingEdit, request: Request, background: BackgroundTasks) -> dict[str, Any]:
    """Approve the posting as shown (with any last edits). Applying opens from now on, and
    public profiles that fit are searched for in the background."""
    state = request.app.state
    _awaiting_posting(request, job_id)
    posting = Posting(**body.model_dump(), approved_at=now())
    state.db.set_job_posting(job_id, posting.model_dump())
    state.db.set_job_step(job_id, JobStep.SOURCING)
    state.bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.SOURCING.value, "posting": "approved"})
    background.add_task(steps.source, state, job_id)
    return job_view(request, job_id)
