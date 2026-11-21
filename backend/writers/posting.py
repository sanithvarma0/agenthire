"""Turns a role brief into a posting (docs/LLD.md, section 17): the role as understood, a job
description, and screening questions in priority order, each with a guide to what a strong,
an average and a weak answer contains. HR edits and approves it before anything else runs.

The input is the role typed on the Hire screen, or the role brief conversation's transcript.
No role, skill or question is written in code; the model writes them from what HR said.
"""

from __future__ import annotations

import json
from typing import Any

from backend.models import Posting, RoleBrief, ScreeningQuestion
from backend.settings import Settings

QUESTIONS = 5

INSTRUCTIONS = f"""You are an experienced recruiter. A hiring manager at the company named below described a role they are hiring for,
typed, or in a conversation with an assistant (USER is the hiring manager, AGENT the assistant). Use what the hiring manager said,
including corrections and the summary they confirmed. Never invent requirements, perks, salary or facts about the company that
were not said; where something was not said, leave it out rather than guess.

Return:
- understood: false only if the text does not say what role is being hired for.
- role: the job title, as a recruiter would write it.
- must_haves: the skills or experience the role cannot do without, as said (short phrases).
- experience: the years or level wanted, as said, or "" if not said.
- location: where the work is and whether remote or hybrid, as said, or "" if not said.
- summary: the role in one or two plain sentences.
- title: the posting's title.
- job_description: a short, plain job description a candidate would read: what the role is, what they would do, and what is needed.
  Plain text with short paragraphs and simple "- " lines; no markdown headings, no emoji, nothing that was not said.
- questions: exactly {QUESTIONS} questions for a 3-minute first screening phone call, in priority order (the most telling first,
  since the call may end before the last). Each is one short spoken question about the candidate's experience with the must-haves,
  answerable in a few sentences on the phone. Do not ask about salary, notice period, location or interest: the call covers those
  separately. Never ask about age, family, religion, caste, health or anything not related to the work.
  For each question, a scoring guide: strong (what a strong answer contains), average, weak. Judge content only, never accent,
  fluency or grammar."""

_GUIDE = {"type": "object", "additionalProperties": False, "required": ["question", "strong", "average", "weak"],
          "properties": {k: {"type": "string"} for k in ("question", "strong", "average", "weak")}}

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["understood", "role", "must_haves", "experience", "location", "summary", "title",
                 "job_description", "questions"],
    "properties": {
        "understood": {"type": "boolean"},
        "role": {"type": "string"},
        "must_haves": {"type": "array", "items": {"type": "string"}},
        "experience": {"type": "string"},
        "location": {"type": "string"},
        "summary": {"type": "string"},
        "title": {"type": "string"},
        "job_description": {"type": "string"},
        "questions": {"type": "array", "items": _GUIDE},
    },
}


class RoleNotUnderstood(ValueError):
    """The text did not say what role is being hired for."""


def write_posting(text: str, company: str, *, client: Any, settings: Settings) -> tuple[RoleBrief, Posting]:
    response = client.chat.completions.create(
        model=settings.secrets.llm_model_smart, reasoning_effort="low",
        messages=[{"role": "system", "content": INSTRUCTIONS},
                  {"role": "user", "content": f"Company: {company}\n\n{text}"}],
        response_format={"type": "json_schema", "json_schema": {"name": "posting", "strict": True, "schema": SCHEMA}},
    )
    data = json.loads(response.choices[0].message.content)
    questions = [ScreeningQuestion(**{k: q[k].strip() for k in ("question", "strong", "average", "weak")})
                 for q in data["questions"] if q["question"].strip()][:QUESTIONS]
    if not data["understood"] or not data["role"].strip() or not questions or len(data["job_description"].strip()) < 20:
        raise RoleNotUnderstood("the text does not say what role is being hired for")
    role = RoleBrief(role=data["role"].strip(), company=company,
                     must_haves=[m.strip() for m in data["must_haves"] if m.strip()],
                     experience=data["experience"].strip(), location=data["location"].strip(),
                     summary=data["summary"].strip())
    posting = Posting(title=data["title"].strip() or role.role, job_description=data["job_description"].strip(),
                      questions=questions)
    return role, posting
