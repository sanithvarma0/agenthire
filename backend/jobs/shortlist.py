"""The shortlist after the screening calls (docs/LLD.md, section 17): every call scored
against the approved guide, every score backed by a quote checked against the transcript,
and the candidates ranked. HR decides; nothing here contacts anyone.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.guardrails import check_fact
from backend.jobs.steps import fail, openai_client
from backend.models import SCREENING_KIND, EventType, JobStep, Outcome
from backend.writers.call_result import transcript_from_events
from backend.writers.scoring import score_call

log = logging.getLogger(__name__)

DETAILS = ("expected_salary", "notice_period", "current_salary", "location")


def build(state: Any, job_id: str) -> None:
    """Score each screening call, rank the candidates, store the shortlist in the job's
    report and finish the job."""
    db, bus = state.db, state.bus
    try:
        job = db.get_job(job_id)
        questions = (job["posting"] or {}).get("questions", [])
        people = {p["id"]: p for p in db.people_view(job_id)}
        entries = []
        for conversation in db.list_conversations(job_id, kind=SCREENING_KIND):
            if conversation["status"] == "blocked" or not conversation.get("result"):
                continue
            entry = _score(state, job_id, conversation, questions, people.get(conversation["person_id"], {}))
            entries.append(entry)
        ranked = sorted(entries, key=_rank_key)
        for i, entry in enumerate(e for e in ranked if e["score"] is not None):
            entry["rank"] = i + 1
        db.set_job_report(job_id, {"shortlist": ranked, "questions": [q["question"] for q in questions]})
        db.set_job_step(job_id, JobStep.DONE)
        bus.publish(job_id, EventType.STEP_CHANGED, {"step": JobStep.DONE.value, "ranked": len(ranked)})
    except Exception as exc:
        log.exception("shortlist failed for %s", job_id)
        fail(state, job_id, f"Couldn't score the calls ({type(exc).__name__}).")


def _score(state: Any, job_id: str, conversation: dict[str, Any], questions: list[dict[str, Any]],
           person: dict[str, Any]) -> dict[str, Any]:
    result = conversation["result"]
    facts = {f["name"]: f for f in result.get("facts", []) if f.get("verified") is not False}
    entry: dict[str, Any] = {
        "person_id": conversation["person_id"], "name": person.get("name", ""),
        "headline": person.get("headline", ""), "conversation_id": conversation["id"],
        "routed": bool(conversation.get("routed_to")), "outcome": result.get("outcome"),
        "details": {k: {"value": facts[k]["value"], "said_as": facts[k]["said_as"]} for k in DETAILS if k in facts},
        "answers": [], "score": None, "scored": 0, "asked": 0, "summary": "", "problems": [],
    }
    answered = [i for i in range(1, len(questions) + 1) if f"answer_{i}" in facts]
    entry["asked"] = len(answered)
    if result.get("outcome") != Outcome.INTERESTED.value or not answered:
        return entry

    transcript = transcript_from_events(db_events(state, job_id, conversation["id"]))
    try:
        scored = score_call(questions, transcript, client=openai_client(state), settings=state.settings)
    except Exception as exc:
        log.exception("scoring failed for %s", conversation["id"])
        entry["problems"].append(f"not scored ({type(exc).__name__})")
        return entry
    by_question: dict[int, dict[str, Any]] = {}
    for item in scored.get("scores", []):
        n, score = int(item.get("question", 0)), int(item.get("score", 0))
        if not 1 <= n <= len(questions) or not 1 <= score <= 5:
            continue
        ok, why = check_fact(item.get("quote", ""), "", item.get("evidence_seq"), transcript)
        if not ok:  # a score must rest on the candidate's own words, or it is not shown
            entry["problems"].append(f"question {n}: score dropped, {why}")
            continue
        by_question[n] = {"score": score, "quote": item["quote"].strip(), "reason": item.get("reason", "").strip()}
    for n in range(1, len(questions) + 1):
        answer = facts.get(f"answer_{n}")
        entry["answers"].append({"question": n, "text": questions[n - 1]["question"],
                                 "answer": answer["value"] if answer else None, **by_question.get(n, {})})
    scores = [a["score"] for a in entry["answers"] if "score" in a]
    if scores:
        entry["score"] = round(sum(scores) / len(scores), 1)
        entry["scored"] = len(scores)
    entry["summary"] = str(scored.get("summary", "")).strip()
    return entry


def db_events(state: Any, job_id: str, conversation_id: str) -> list:
    return state.db.list_events(job_id, conversation_id=conversation_id)


def _rank_key(entry: dict[str, Any]) -> tuple:
    """Scored candidates first, best mean first, more questions answered breaking a tie;
    then the rest (not interested, not reached) in the order they were called."""
    if entry["score"] is None:
        return (1, 0.0, 0)
    return (0, -entry["score"], -entry["scored"])
