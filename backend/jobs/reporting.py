"""The reporting step (docs/LLD.md, section 7): compare the call results and recommend
one provider, then wait for the user to pick."""

from __future__ import annotations

import logging
from typing import Any

from backend.guardrails import local_now
from backend.jobs.steps import fail, openai_client
from backend.models import EventType, JobStep
from backend.writers.comparison import Candidate, write_comparison

log = logging.getLogger(__name__)


def candidates(state: Any, job_id: str) -> list[Candidate]:
    """Each called provider with their checked result. Facts the grounding check could
    not confirm are left out, so the comparison only weighs what was really said."""
    people = {p.id: p for p in state.db.list_people(job_id)}
    out = []
    for conv in state.db.list_conversations(job_id, kind="home_call"):
        result, person = conv.get("result"), people.get(conv.get("person_id"))
        if not result or person is None:
            continue
        facts = {f["name"]: f["value"] for f in result.get("facts", []) if f.get("verified") is not False}
        out.append(Candidate(
            person_id=person.id, name=person.name, outcome=result["outcome"],
            earliest_time=facts.get("earliest_time"), visiting_charge=facts.get("visiting_charge"),
            notes=result.get("notes", ""), distance_km=person.distance_km, rating=person.rating,
            review_count=person.review_count))
    return out


def report(state: Any, job_id: str) -> None:
    db, bus, settings = state.db, state.bus, state.settings
    try:
        comparison = write_comparison(candidates(state, job_id), client=openai_client(state), settings=settings,
                                      now=local_now(settings).replace(tzinfo=None))
    except Exception as exc:
        log.exception("comparison failed for %s", job_id)
        return fail(state, job_id, f"Couldn't compare the answers ({type(exc).__name__}). Try again.")
    db.set_job_report(job_id, comparison.model_dump(include={"recommended_person_id", "reasoning"}))
    db.set_job_step(job_id, JobStep.AWAITING_PICK)
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.AWAITING_PICK.value,
                                                 "recommended": comparison.recommended_person_id})
