"""The typed objects that flow between AgentHire's components.

Every hand-off between components is one of these objects, never free text that
code has to interpret. Free text exists in only two places: what is spoken
aloud, and the transcript (see docs/HLD.md, section 6).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Side(StrEnum):
    HOME = "home"
    COMPANY = "company"


class Language(StrEnum):
    TELUGU = "te"
    HINDI = "hi"
    ENGLISH = "en"


class JobStep(StrEnum):
    """Steps of a job (docs/LLD.md, sections 7 and 17). Home: briefing, finding,
    awaiting_approval, calling, reporting, awaiting_pick, confirming, done. Company:
    briefing, writing, awaiting_posting, sourcing, awaiting_approval, calling, scoring, done."""

    BRIEFING = "briefing"
    FINDING = "finding"
    AWAITING_APPROVAL = "awaiting_approval"
    CALLING = "calling"
    REPORTING = "reporting"
    AWAITING_PICK = "awaiting_pick"
    CONFIRMING = "confirming"
    DONE = "done"
    WRITING = "writing"
    AWAITING_POSTING = "awaiting_posting"
    SOURCING = "sourcing"
    SCORING = "scoring"


class PersonRole(StrEnum):
    PROVIDER = "provider"
    CANDIDATE = "candidate"


class ConversationStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ENDED = "ended"
    BLOCKED = "blocked"  # a guardrail refused to start it


class Outcome(StrEnum):
    """How a call ended. A conversation kind uses only its own set (`outcome_meanings`)."""

    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    WRONG_NUMBER = "wrong_number"
    CALL_CUSTOMER = "call_customer"  # they want to speak to the customer directly
    DECLINED = "declined"
    NO_ANSWER = "no_answer"
    # Screening calls (company side)
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    CALL_LATER = "call_later"


# What each outcome means. Shared by the live agent's tools and the result
# writer, so both judge a call by the same definitions. When nobody spoke at
# all, `no_answer` is also set in code without asking a model.
OUTCOME_MEANINGS = {
    Outcome.NO_ANSWER: "no person answered: the phone was not picked up, or only voicemail or a recorded "
                       "message answered",
    Outcome.AVAILABLE: "they can take the job",
    Outcome.NOT_AVAILABLE: "they cannot take the job, for example because they are too busy or it is not their kind "
                           "of work, even if they say so politely",
    Outcome.WRONG_NUMBER: "this is not a provider of this kind of work, or not who was meant to be called",
    Outcome.CALL_CUSTOMER: "they want to speak to the person who needs the work directly",
    Outcome.DECLINED: "they refused to talk at all, or asked not to be called again",
}

# The same for a screening call to a candidate (docs/LLD.md, section 17).
SCREENING_OUTCOME_MEANINGS = {
    Outcome.NO_ANSWER: OUTCOME_MEANINGS[Outcome.NO_ANSWER],
    Outcome.INTERESTED: "they are interested in the role and took the screening questions",
    Outcome.NOT_INTERESTED: "they are not interested in the role, or not looking for a change",
    Outcome.CALL_LATER: "they are interested but cannot talk now and asked to be called another time",
    Outcome.WRONG_NUMBER: "the person who answered is not the candidate named",
    Outcome.DECLINED: "they refused to talk at all, or asked not to be called again",
}

SCREENING_KIND = "screening_call"

# Outcomes that mean the person is taking part, and so must be asked every required fact.
TAKING_PART = (Outcome.AVAILABLE, Outcome.INTERESTED)
# Outcomes that settle a conversation with nothing more to find.
SETTLED = (Outcome.NOT_AVAILABLE, Outcome.NOT_INTERESTED, Outcome.CALL_LATER, Outcome.WRONG_NUMBER,
           Outcome.DECLINED, Outcome.NO_ANSWER)


def outcome_meanings(kind: str) -> dict[Outcome, str]:
    """The outcomes a conversation kind may end with, and what each means."""
    return SCREENING_OUTCOME_MEANINGS if kind == SCREENING_KIND else OUTCOME_MEANINGS


class EventType(StrEnum):
    """Every kind of entry in a job's event stream (docs/LLD.md, section 11)."""

    STEP_CHANGED = "step_changed"
    CONVERSATION_STARTED = "conversation_started"
    AGENT_SAID = "agent_said"
    PERSON_SAID = "person_said"
    TOOL_CALLED = "tool_called"
    FACT_RECORDED = "fact_recorded"
    OUTCOME_SET = "outcome_set"
    OPENING_CHECKED = "opening_checked"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    CONVERSATION_ENDED = "conversation_ended"
    RESULT_READY = "result_ready"
    MESSAGE_SENT = "message_sent"
    LANGUAGE_CHANGED = "language_changed"
    CALL_ROUTED = "call_routed"
    AVATAR_READY = "avatar_ready"  # the brief's avatar has joined and is showing


class JobStart(BaseModel):
    """What the Start screen sends: the chosen language and where the work is.

    No preferred time or budget (builder's decision): providers say when they can
    come and what they charge, and the user chooses."""

    language: Language = Field(description="Language the brief starts in; provider calls start in it too")
    address: str = Field(min_length=5, max_length=300, description="Full address, as the user confirmed it")
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    area: str = Field(min_length=2, max_length=200, description="Colony, locality and city, as spoken on calls")
    request: str | None = Field(default=None, max_length=1000,
                                description="A typed request, until the voice brief exists")


class RoleStart(BaseModel):
    """What the Hire screen sends to start a company job (docs/LLD.md, section 17)."""

    company: str = Field(min_length=2, max_length=100, description="The hiring company's name, as said on calls")
    request: str | None = Field(default=None, max_length=2000,
                                description="The role typed instead of described by voice")


class RoleBrief(BaseModel):
    """The role as understood from the role brief."""

    role: str = Field(description="The job title")
    company: str
    must_haves: list[str] = Field(default_factory=list, description="Skills or experience the role cannot do without")
    experience: str = Field(default="", description="Years or level of experience wanted, as said")
    location: str = Field(default="", description="Where the work is, and whether remote or hybrid, as said")
    summary: str = Field(description="The role in one or two plain sentences")


class ScreeningQuestion(BaseModel):
    """One screening question and the guide its answers are scored against."""

    question: str = Field(min_length=3, max_length=400)
    strong: str = Field(default="", max_length=600, description="What a strong answer contains")
    average: str = Field(default="", max_length=600, description="What an average answer contains")
    weak: str = Field(default="", max_length=600, description="What a weak answer looks like")


class Posting(BaseModel):
    """The job description, the screening questions in priority order and their scoring
    guide. HR edits and approves it before anyone is sourced or called."""

    title: str = Field(min_length=2, max_length=120)
    job_description: str = Field(min_length=20, max_length=6000)
    questions: list[ScreeningQuestion] = Field(min_length=1, max_length=5)
    approved_at: str | None = None


class Brief(BaseModel):
    """What the user asked for, as understood from the brief."""

    service: str = Field(description="The kind of help needed, in the user's own terms")
    work: str = Field(description="What needs doing")
    extra_questions: list[str] = Field(
        default_factory=list, description="Job-specific questions generated from the brief"
    )


class Person(BaseModel):
    """A provider or a candidate found for a job."""

    id: str
    job_id: str
    role: PersonRole
    name: str
    phone: str | None = None
    source: str
    rating: float | None = None
    review_count: int | None = None
    address: str | None = None
    distance_km: float | None = None


class FactSpec(BaseModel):
    """One thing a conversation has to find out."""

    name: str = Field(description="Short identifier, used when the fact is recorded")
    description: str = Field(description="What to find out, in plain words")
    required: bool = True


class ConversationRecord(BaseModel):
    """Everything the voice agent is given for one conversation.

    The agent can only share what is in `shareable`. Things it must not reveal,
    such as the customer's full address, are never put in the record at all, so
    the prompt cannot leak them; `withheld` only tells the agent how to answer
    if it is asked for them.
    """

    kind: str = Field(description="An entry name from voice/kinds.yaml")
    language: Language
    goal: str
    facts_to_collect: list[FactSpec]
    shareable: dict[str, str] = Field(default_factory=dict, description="Label to value")
    withheld: list[str] = Field(default_factory=list, description="Descriptions only, no values")
    known: list[str] = Field(default_factory=list, description="Memory recalled before the call")
    opening_requirements: list[str] = Field(default_factory=list)
    second_turn_requirements: list[str] = Field(default_factory=list, description="Once they confirm who answered")
    time_cap_seconds: int
    wrap_up_at_seconds: int | None = Field(
        default=None, description="When the agent is told to start closing the conversation"
    )


class CollectedFact(BaseModel):
    """A fact found in a conversation, with where it came from."""

    name: str
    value: str = Field(description="Normalised value, for example an amount in rupees")
    said_as: str = Field(description="The words the person used")
    evidence_seq: int | None = Field(
        default=None, description="Sequence number of the transcript event it came from"
    )
    verified: bool | None = Field(
        default=None, description="Set by the grounding check; None until it has run"
    )


class TranscriptLine(BaseModel):
    """One spoken line of a conversation, numbered by its event sequence."""

    seq: int
    speaker: str = Field(description="agent or person")
    text: str


class CallResult(BaseModel):
    """The structured result of one call, built from its transcript."""

    outcome: Outcome
    facts: list[CollectedFact] = Field(default_factory=list)
    notes: str = ""
    language_spoken: Language | None = None
    do_not_call: bool = Field(default=False, description="They asked not to be called again")

    def fact(self, name: str) -> CollectedFact | None:
        return next((f for f in self.facts if f.name == name), None)


class ComparisonRow(BaseModel):
    person_id: str
    name: str
    result: CallResult


class Comparison(BaseModel):
    """The call results for a job side by side, with a recommendation."""

    rows: list[ComparisonRow]
    recommended_person_id: str | None = None
    reasoning: str = ""


class Event(BaseModel):
    """One entry in a job's ordered event stream."""

    id: int
    job_id: str
    conversation_id: str | None
    seq: int
    type: str
    payload: dict[str, Any]
    created_at: str
