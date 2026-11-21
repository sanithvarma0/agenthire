"""Job steps that run in the back end (docs/LLD.md, section 7). Each step moves the
job on and announces it on the job's event stream, or records why it could not."""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.db import new_id
from backend.finders.places import find_providers
from backend.models import EventType, JobStep, Person, PersonRole
from backend.writers.brief import BriefNotUnderstood, write_brief
from backend.writers.posting import RoleNotUnderstood, write_posting
from backend.writers.sourcing import find_profiles

log = logging.getLogger(__name__)

SOURCED = "web"  # found by the web crawl: no phone number; a screening call rings the builder instead


def openai_client(state: Any) -> Any:
    """One OpenAI client per app, made when first needed (tests put a fake one on the state)."""
    if getattr(state, "openai", None) is None:
        from openai import OpenAI
        state.openai = OpenAI(api_key=state.settings.secrets.openai_api_key)
    return state.openai


def fail(state: Any, job_id: str, reason: str) -> None:
    state.db.set_job_error(job_id, reason)
    job = state.db.get_job(job_id)
    state.bus.publish(job_id, EventType.STEP_CHANGED, {"step": job["step"], "error": reason})


def write_role(state: Any, job_id: str, said: str | None = None) -> None:
    """Company side, briefing to awaiting the posting's approval (docs/LLD.md, section 17):
    write the job description, screening questions and scoring guide from the typed role or
    the role brief's transcript in `said`."""
    db, bus, settings = state.db, state.bus, state.settings
    start = db.get_job(job_id)["start"] or {}
    db.set_job_step(job_id, JobStep.WRITING)
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.WRITING.value})
    try:
        role, posting = write_posting(said or start.get("request") or "", start.get("company", ""),
                                      client=openai_client(state), settings=settings)
    except RoleNotUnderstood:
        return fail(state, job_id, "Couldn't tell what role this is for. Start again and describe the role.")
    except Exception as exc:
        log.exception("posting writer failed for %s", job_id)
        return fail(state, job_id, f"Couldn't write the job description ({type(exc).__name__}). Try again.")
    db.set_job_brief(job_id, role.model_dump())
    db.set_job_posting(job_id, posting.model_dump())
    db.set_job_step(job_id, JobStep.AWAITING_POSTING)
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.AWAITING_POSTING.value, "role": role.role})


def source(state: Any, job_id: str) -> None:
    """Company side, after the posting is approved: find public profiles that fit it and
    store them as candidates (`source = web`, no phone). A crawl that fails or finds nobody
    does not fail the job; it is noted for the screen."""
    db, bus, settings = state.db, state.bus, state.settings
    job = db.get_job(job_id)
    started = time.perf_counter()
    note: dict[str, Any] = {"found": 0, "error": None}
    try:
        profiles = find_profiles(job["brief"] or {}, job["posting"] or {}, client=openai_client(state), settings=settings)
    except Exception as exc:
        log.exception("sourcing failed for %s", job_id)
        profiles, note["error"] = [], f"The web crawl did not work this time ({type(exc).__name__})."
    for p in profiles:
        person = Person(id=new_id("per"), job_id=job_id, role=PersonRole.CANDIDATE, name=p.name, phone=None,
                        source=SOURCED, address=p.location or None)
        db.add_person(person, raw=p.model_dump(exclude={"name"}))
    note.update(found=len(profiles), seconds=round(time.perf_counter() - started, 1))
    db.set_job_search(job_id, {"sourced": note})
    db.set_job_step(job_id, JobStep.AWAITING_APPROVAL)
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.AWAITING_APPROVAL.value, "sourced": note["found"]})


def find(state: Any, job_id: str, said: str | None = None) -> None:
    """Briefing to awaiting approval: understand the request (typed, or the voice brief's
    transcript in `said`), then find providers near the user and store them best first."""
    db, bus, settings = state.db, state.bus, state.settings
    job = db.get_job(job_id)
    start = job["start"] or {}
    try:
        brief = write_brief(said or start.get("request") or "", client=openai_client(state), settings=settings)
    except BriefNotUnderstood:
        return fail(state, job_id, "Couldn't tell what needs fixing. Start again and describe the problem.")
    except Exception as exc:  # a model or network failure: say so rather than hang
        log.exception("brief writer failed for %s", job_id)
        return fail(state, job_id, f"Couldn't read the request ({type(exc).__name__}). Try again.")
    db.set_job_brief(job_id, brief.model_dump())
    db.set_job_step(job_id, JobStep.FINDING)
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.FINDING.value, "brief": brief.model_dump(),
                                                 "radius_km": settings.providers.search_radius_km})

    try:
        result = find_providers(brief.service, start["lat"], start["lng"], settings=settings,
                                http=getattr(state, "http", None))
    except Exception as exc:
        log.exception("finder failed for %s", job_id)
        return fail(state, job_id, f"Couldn't search for providers ({type(exc).__name__}). Try again.")
    if not result.providers:
        return fail(state, job_id, f"No {brief.service} with a phone number within {result.radius_km:g} km.")

    for provider in result.providers:
        person = Person(id=new_id("per"), job_id=job_id, role=PersonRole.PROVIDER, name=provider.name,
                        phone=provider.phone, source="google_places", rating=provider.rating,
                        review_count=provider.review_count, address=provider.address,
                        distance_km=provider.distance_km)
        db.add_person(person, raw=provider.model_dump(include={"place_id", "lat", "lng", "open_now",
                                                               "primary_type", "maps_url"}))
    db.set_job_search(job_id, {"service": brief.service, "radius_km": result.radius_km,
                               "area": result.area.model_dump(), "call_top": settings.providers.call_top})
    db.set_job_step(job_id, JobStep.AWAITING_APPROVAL)
    bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.AWAITING_APPROVAL.value,
                                                 "found": len(result.providers), "radius_km": result.radius_km})
