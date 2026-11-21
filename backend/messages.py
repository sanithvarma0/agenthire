"""Sending text messages. Only the back end sends, and every message goes through
`can_message` first, which follows the test-mode toggle like calls do.

SMS goes through Twilio's REST API with httpx (no extra library). Tests put a fake
sender on `app.state.sms`.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from backend.guardrails import can_message, normalise_phone
from backend.models import EventType, Person
from backend.settings import Settings

log = logging.getLogger(__name__)

TWILIO_MESSAGES = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class SmsSender(Protocol):
    def send(self, *, to: str, body: str) -> str: ...  # returns the provider's message id


class TwilioSms:
    def __init__(self, settings: Settings):
        self._s = settings.secrets

    def send(self, *, to: str, body: str) -> str:
        response = httpx.post(
            TWILIO_MESSAGES.format(sid=self._s.twilio_account_sid), timeout=20,
            auth=(self._s.twilio_account_sid, self._s.twilio_auth_token),
            data={"To": to, "From": self._s.twilio_phone_number, "Body": body},
        )
        if response.status_code >= 300:
            raise RuntimeError(f"Twilio {response.status_code}: {response.text[:200]}")
        return response.json().get("sid", "")


def sms_sender(state: Any) -> SmsSender:
    if getattr(state, "sms", None) is None:
        state.sms = TwilioSms(state.settings)
    return state.sms


def send_sms(state: Any, job_id: str, person: Person, body: str) -> dict[str, Any]:
    """Send one SMS to a provider for a job, through the guardrail. Recorded in the
    messages table and announced as `message_sent`, whether it went or was refused."""
    db, bus = state.db, state.bus
    decision = can_message(person.phone or "", job_id, db=db, settings=state.settings)
    to = normalise_phone(person.phone or "")
    if not decision.allowed:
        status = f"refused: {decision.reason}"
    else:
        try:
            sms_sender(state).send(to=decision.dial_to, body=body)
            status = "sent"
        except Exception as exc:
            log.warning("SMS to %s failed: %s", person.id, exc)
            status = f"failed: {type(exc).__name__}"
    routed_to = decision.dial_to if decision.routed else ""
    message_id = db.add_message(job_id, "sms", to, routed_to, body, status, person_id=person.id)
    payload = {"message_id": message_id, "person_id": person.id, "channel": "sms", "status": status,
               "routed": decision.routed, "body": body}
    bus.publish(job_id, EventType.MESSAGE_SENT, payload)
    return payload
