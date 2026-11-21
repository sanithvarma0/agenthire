"""Guardrails enforced in code (docs/LLD.md, section 10).

Before dialling: every call goes through `can_dial`, which refuses with a reason.
After a call: `ground_call_result` checks every fact against the transcript line
it cites. A fact that fails stays in the result but is marked unverified, and
the app shows it as "not confirmed", never as fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.db import Database
from backend.models import CallResult, TranscriptLine
from backend.settings import Settings
from backend.text_match import numbers, quote_in_line

HOME_CALL_KIND = "home_call"


def normalise_phone(number: str) -> str:
    """An Indian phone number in +91XXXXXXXXXX form, whatever spaces or prefixes it came with.
    Other numbers keep their + and digits."""
    digits = re.sub(r"\D", "", number or "")
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return "+" + digits if digits else ""


@dataclass(frozen=True)
class DialDecision:
    """Whether to call, and which phone actually rings."""

    allowed: bool
    reason: str = ""
    dial_to: str = ""     # the number that will ring
    routed: bool = False  # True when test mode sends a provider's call to the builder's own phone


def can_dial(number: str, job_id: str, *, db: Database, settings: Settings, now: datetime | None = None,
             kind: str = HOME_CALL_KIND) -> DialDecision:
    """Whether this provider may be called for this job now, and which phone rings.

    Test mode is the demo toggle: providers are found for real, but every call
    rings DEMO_ROUTE_PHONE (the builder, playing the provider) instead of them.
    With it off, the provider's own phone rings. Checks, in order:

    1. Test mode: DEMO_ROUTE_PHONE must be one of the builder's own numbers (ALLOWED_NUMBERS).
    2. The user approved this provider's number for this job.
    3. Calling hours, for whichever phone will ring. The builder's own numbers are
       exempt: the rule protects people who did not ask to be called.
    4. The provider has not asked not to be called again.
    5. The job has not used up its calls.
    """
    phone = normalise_phone(number)
    own_numbers = {normalise_phone(n) for n in settings.allowed_numbers}
    if not phone:
        return DialDecision(False, "no phone number")

    dial_to, routed = phone, False
    if settings.test_mode:
        route = normalise_phone(settings.demo_route_phone)
        if not route or route not in own_numbers:
            return DialDecision(False, "test mode is on, but DEMO_ROUTE_PHONE is not one of ALLOWED_NUMBERS")
        dial_to, routed = route, route != phone

    if not any(normalise_phone(p.phone or "") == phone for p in db.list_people(job_id, approved_only=True)):
        return DialDecision(False, "the user has not approved this number for this job")
    if dial_to not in own_numbers and not within_calling_hours(settings, now):
        return DialDecision(False, f"outside calling hours ({settings.calling.hours_start} to "
                                   f"{settings.calling.hours_end}, {settings.calling.timezone})")
    if db.get_facts("provider", phone).get("do_not_call") == "true":
        return DialDecision(False, "this number asked not to be called again")
    if db.count_calls(job_id, kind) >= settings.calling.max_calls_per_job:
        return DialDecision(False, f"this job has used all {settings.calling.max_calls_per_job} of its calls")
    return DialDecision(True, "", dial_to, routed)


def can_dial_fallback(person_id: str, job_id: str, *, db: Database, settings: Settings,
                      kind: str) -> DialDecision:
    """Whether a screening call for a candidate with no phone number may ring the builder.

    Candidates found by web crawling have no number (none is ever taken), so their screening
    call always rings DEMO_ROUTE_PHONE, whatever the test mode, and the builder answers as
    them (builder's decision, Sun 22 Nov; docs/LLD.md, section 17). Checks, in order:

    1. DEMO_ROUTE_PHONE is one of the builder's own numbers (ALLOWED_NUMBERS).
    2. HR approved this candidate for this job.
    3. The job has not used up its calls.
    Calling hours do not apply: only the builder's own phone rings.
    """
    own_numbers = {normalise_phone(n) for n in settings.allowed_numbers}
    route = normalise_phone(settings.demo_route_phone)
    if not route or route not in own_numbers:
        return DialDecision(False, "no number for this candidate, and DEMO_ROUTE_PHONE is not one of ALLOWED_NUMBERS")
    if not any(p.id == person_id for p in db.list_people(job_id, approved_only=True)):
        return DialDecision(False, "this candidate was not approved for a call on this job")
    if db.count_calls(job_id, kind) >= settings.calling.max_calls_per_job:
        return DialDecision(False, f"this job has used all {settings.calling.max_calls_per_job} of its calls")
    return DialDecision(True, "", route, True)


def can_message(number: str, job_id: str, *, db: Database, settings: Settings) -> DialDecision:
    """Whether a message may go to this provider for this job, and to which phone.
    The same toggle as calls: in test mode it goes to the builder's own phone. Only
    a provider the user approved for this job is ever messaged."""
    phone = normalise_phone(number)
    own_numbers = {normalise_phone(n) for n in settings.allowed_numbers}
    if not phone:
        return DialDecision(False, "no phone number")
    send_to, routed = phone, False
    if settings.test_mode:
        route = normalise_phone(settings.demo_route_phone)
        if not route or route not in own_numbers:
            return DialDecision(False, "test mode is on, but DEMO_ROUTE_PHONE is not one of ALLOWED_NUMBERS")
        send_to, routed = route, route != phone
    if not any(normalise_phone(p.phone or "") == phone for p in db.list_people(job_id, approved_only=True)):
        return DialDecision(False, "the user has not approved this number for this job")
    if db.get_facts("provider", phone).get("do_not_call") == "true":
        return DialDecision(False, "this number asked not to be contacted again")
    return DialDecision(True, "", send_to, routed)


def _zone(name: str) -> tzinfo:
    """The time zone by name. Windows has no zone database without an extra
    package; India has no daylight saving, so its fixed offset is exact."""
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name in ("Asia/Kolkata", "Asia/Calcutta"):
            return timezone(timedelta(hours=5, minutes=30), name)
        raise


def local_now(settings: Settings) -> datetime:
    """The time where the calls happen (India), whatever the server's own clock zone."""
    return datetime.now(_zone(settings.calling.timezone))


def within_calling_hours(settings: Settings, now: datetime | None = None) -> bool:
    zone = _zone(settings.calling.timezone)
    local = (now or datetime.now(zone)).astimezone(zone).time()
    start, end = (time.fromisoformat(settings.calling.hours_start), time.fromisoformat(settings.calling.hours_end))
    return start <= local < end


def check_fact(said_as: str, value: str, evidence_seq: int | None,
               transcript: list[TranscriptLine]) -> tuple[bool, str]:
    """Whether one fact is backed by the line it cites, and why not if it is not."""
    line = next((t for t in transcript if t.seq == evidence_seq), None)
    if line is None:
        return False, "cites no line of this call"
    if line.speaker != "person":
        return False, "cites the agent, not the person"
    if not quote_in_line(said_as, line.text):
        return False, "the quote is not in the cited line"
    # Only a value that is itself a number or a time can contradict a spoken
    # number; "yes" quoted from "yes, I can come at 11" is fine.
    quoted_numbers, value_numbers = numbers(said_as), numbers(value)
    if quoted_numbers and value_numbers and not _any_number_carried(quoted_numbers, value_numbers):
        return False, "the value does not match the number the person said"
    return True, ""


def _any_number_carried(quoted: set[int], value: set[int]) -> bool:
    """Whether a number the person said appears in the value. "4 o'clock" may
    become 16:00, so an hour from 1 to 12 also matches the same hour plus 12."""
    return any(n in value or (1 <= n <= 12 and n + 12 in value) for n in quoted)


def ground_call_result(result: CallResult, transcript: list[TranscriptLine]) -> tuple[CallResult, list[str]]:
    """Mark each fact verified or not. Returns the result and a list of problems found."""
    problems: list[str] = []
    grounded = []
    for fact in result.facts:
        ok, reason = check_fact(fact.said_as, fact.value, fact.evidence_seq, transcript)
        if not ok:
            problems.append(f"{fact.name}: {reason}")
        grounded.append(fact.model_copy(update={"verified": ok}))
    return result.model_copy(update={"facts": grounded}), problems
