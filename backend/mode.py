"""The test-mode switch (builder's decision, Sun 22 Nov).

Test mode on: every call and SMS goes to DEMO_ROUTE_PHONE. Off: the real providers found on
Google Maps are called and messaged, still only after the user's approval and within every
other guardrail (calling hours, do-not-call, the calls a job may make). Screening calls ring
the builder either way, as no candidate's number is ever taken.

The switch is locked unless TEST_MODE_PIN is set in .env, and it needs that PIN. It changes
only this running back end: a restart goes back to TEST_MODE from .env. It refuses while a
job is calling, so a call never changes its routing half way through. The deployed server
sets no PIN and does not route /mode at all, so it stays in test mode.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.models import JobStep

router = APIRouter()
BUSY = (JobStep.CALLING.value, JobStep.CONFIRMING.value)


def mode_view(request: Request) -> dict[str, bool]:
    settings = request.app.state.settings
    return {"test_mode": settings.test_mode, "switchable": bool(settings.test_mode_pin)}


@router.get("/mode")
def get_mode(request: Request) -> dict[str, bool]:
    return mode_view(request)


class ModeChange(BaseModel):
    test_mode: bool
    pin: str


@router.post("/mode")
def set_mode(body: ModeChange, request: Request) -> dict[str, bool]:
    state = request.app.state
    pin = state.settings.test_mode_pin
    if not pin:
        raise HTTPException(status_code=403, detail="the switch is locked: no TEST_MODE_PIN is set")
    if not hmac.compare_digest(body.pin.encode(), pin.encode()):
        raise HTTPException(status_code=403, detail="wrong PIN")
    busy = [j["id"] for j in state.db.list_jobs(limit=50) if j["status"] == "active" and j["step"] in BUSY]
    if busy:
        raise HTTPException(status_code=409, detail="a job is calling right now; switch when it is done")
    state.settings.test_mode = body.test_mode
    return mode_view(request)
