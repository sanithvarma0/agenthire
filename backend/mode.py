"""The test-mode switch (builder's decision, Sun 22 Nov).

Test mode on: every call and SMS goes to DEMO_ROUTE_PHONE. Off: the real providers found on
Google Maps are called and messaged, still only after the user's approval and within every
other guardrail (calling hours, do-not-call, the calls a job may make). Screening calls ring
the builder either way, as no candidate's number is ever taken.

The switch is locked unless TEST_MODE_PIN is set in .env, and it needs that PIN. It changes
only this running back end: a restart goes back to TEST_MODE from .env. It refuses while a
job is calling, so a call never changes its routing half way through. After MAX_WRONG wrong
PINs it stays locked for LOCKOUT_SECONDS, so a short PIN cannot be guessed on the public
server (builder's decision, Sun 22 Nov: the live server has the switch, PIN set by the
builder). The submission zip ships no PIN, so a judge's copy stays in test mode.
"""

from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.models import JobStep

router = APIRouter()
BUSY = (JobStep.CALLING.value, JobStep.CONFIRMING.value)
MAX_WRONG = 5
LOCKOUT_SECONDS = 600


class Lockout:
    """Wrong PINs counted for the whole back end; the switch locks after MAX_WRONG."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.wrong, self.until = clock, 0, 0.0

    def locked(self) -> bool:
        return self.clock() < self.until

    def failed(self) -> None:
        self.wrong += 1
        if self.wrong >= MAX_WRONG:
            self.until, self.wrong = self.clock() + LOCKOUT_SECONDS, 0

    def passed(self) -> None:
        self.wrong = 0


def lockout(state) -> Lockout:
    if not hasattr(state, "mode_lockout"):
        state.mode_lockout = Lockout()
    return state.mode_lockout


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
    guard = lockout(state)
    if guard.locked():
        raise HTTPException(status_code=429, detail="too many wrong PINs; try again in 10 minutes")
    if not hmac.compare_digest(body.pin.encode(), pin.encode()):
        guard.failed()
        raise HTTPException(status_code=403, detail="wrong PIN")
    guard.passed()
    busy = [j["id"] for j in state.db.list_jobs(limit=50) if j["status"] == "active" and j["step"] in BUSY]
    if busy:
        raise HTTPException(status_code=409, detail="a job is calling right now; switch when it is done")
    state.settings.test_mode = body.test_mode
    return mode_view(request)
