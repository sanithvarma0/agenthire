"""Placing calls. Only the back end dials, and every dial goes through `can_dial`
(docs/HLD.md, layer rules).

`place_call` checks the guardrails, records the conversation, then asks LiveKit
to open a room, send the voice worker into it, and ring the phone. It does not
wait for the phone to be answered: the worker does that, and reports
"no answer" if nobody picks up.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Protocol

from backend.db import Database
from backend.events import EventBus
from backend.guardrails import can_dial, can_dial_fallback, normalise_phone
from backend.models import ConversationRecord, EventType, Person, PersonRole
from backend.settings import Settings

log = logging.getLogger("agenthire.calls")

AGENT_JOIN_SECONDS = 15  # how long to wait for the voice agent to join before giving up on a call


class Dialler(Protocol):
    async def dial(self, *, room: str, metadata: dict[str, Any], to: str) -> None: ...

    async def hang_up(self, *, room: str) -> None: ...

    async def open_room(self, *, room: str, metadata: dict[str, Any]) -> None: ...

    def browser_token(self, *, room: str, identity: str) -> str: ...


class LiveKitDialler:
    """Opens the room, dispatches the voice worker into it, and rings the phone."""

    def __init__(self, settings: Settings):
        self._settings = settings

    async def dial(self, *, room: str, metadata: dict[str, Any], to: str) -> None:
        from livekit import api

        s = self._settings.secrets
        lk = api.LiveKitAPI(s.livekit_url, s.livekit_api_key, s.livekit_api_secret)
        try:
            await lk.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=60))
            await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                agent_name=self._settings.voice.agent_name, room=room, metadata=json.dumps(metadata)))
            # Ring the phone only once the agent is in the room. On a real call the phone
            # rang while the worker was restarting, and the person picked up to silence.
            if not await self._agent_joined(lk, room):
                await lk.room.delete_room(api.DeleteRoomRequest(room=room))
                raise RuntimeError(f"no voice agent joined the call room within {AGENT_JOIN_SECONDS} s")
            await lk.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                sip_trunk_id=s.livekit_sip_outbound_trunk_id, sip_call_to=to, room_name=room,
                participant_identity="phone", participant_name="Phone",
                wait_until_answered=False, play_dialtone=False))
        finally:
            await lk.aclose()

    @staticmethod
    async def _agent_joined(lk: Any, room: str) -> bool:
        from livekit import api

        loop = asyncio.get_running_loop()
        deadline = loop.time() + AGENT_JOIN_SECONDS
        while loop.time() < deadline:
            found = await lk.room.list_participants(api.ListParticipantsRequest(room=room))
            if any(p.kind == api.ParticipantInfo.AGENT for p in found.participants):
                return True
            await asyncio.sleep(0.5)
        return False

    async def open_room(self, *, room: str, metadata: dict[str, Any]) -> None:
        """A room for a conversation in the browser (the voice brief): the worker is sent
        in, and the user joins from the web app with `browser_token`. No phone is rung."""
        from livekit import api

        s = self._settings.secrets
        lk = api.LiveKitAPI(s.livekit_url, s.livekit_api_key, s.livekit_api_secret)
        try:
            await lk.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=120))
            await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                agent_name=self._settings.voice.agent_name, room=room, metadata=json.dumps(metadata)))
        finally:
            await lk.aclose()

    def browser_token(self, *, room: str, identity: str) -> str:
        """A short-lived token that lets the web app join one room with its microphone."""
        from datetime import timedelta

        from livekit import api

        s = self._settings.secrets
        return (api.AccessToken(s.livekit_api_key, s.livekit_api_secret)
                .with_identity(identity).with_name("You").with_ttl(timedelta(minutes=15))
                .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
                .to_jwt())

    async def hang_up(self, *, room: str) -> None:
        """End a call by closing its room; the worker then reports the conversation ended."""
        from livekit import api

        s = self._settings.secrets
        lk = api.LiveKitAPI(s.livekit_url, s.livekit_api_key, s.livekit_api_secret)
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room))
        finally:
            await lk.aclose()


def room_name(conversation_id: str) -> str:
    return f"call-{conversation_id}"


async def place_call(*, db: Database, bus: EventBus, settings: Settings, dialler: Dialler, job_id: str,
                     person: Person, record: ConversationRecord,
                     now: datetime | None = None) -> tuple[str, str | None]:
    """Try to call one person for one job.

    Returns the conversation id and, if the call was refused or could not be
    placed, the reason. A refused call is kept as a `blocked` conversation and a
    `guardrail_blocked` event, so the user can see why it did not happen.
    """
    number = normalise_phone(person.phone or "")
    # Check before recording this conversation, or it would count against its own job's call cap.
    if not number and person.role == PersonRole.CANDIDATE:
        # A crawled candidate has no number: the call rings the builder, who answers as them.
        decision = can_dial_fallback(person.id, job_id, db=db, settings=settings, kind=record.kind)
    else:
        decision = can_dial(number, job_id, db=db, settings=settings, now=now, kind=record.kind)
    conversation_id = db.create_conversation(job_id, record.kind, record.language.value,
                                             record.model_dump(mode="json"), person_id=person.id)
    if not decision.allowed:
        db.set_conversation_status(conversation_id, "blocked")
        bus.publish(job_id, EventType.GUARDRAIL_BLOCKED, {"person_id": person.id, "reason": decision.reason},
                    conversation_id)
        log.info("Call to %s refused: %s", person.id, decision.reason)
        return conversation_id, decision.reason

    if decision.routed:
        # Test mode, or a candidate with no number: the builder answers in their place.
        # Marked, so a quote given in the demo is never shown or remembered as theirs.
        db.set_conversation_routed_to(conversation_id, decision.dial_to)
        bus.publish(job_id, EventType.CALL_ROUTED, {"person_id": person.id, "routed_to": "builder"},
                    conversation_id)
    db.set_conversation_status(conversation_id, "active")
    try:
        await dialler.dial(room=room_name(conversation_id), to=decision.dial_to,
                           metadata={"conversation_id": conversation_id, "job_id": job_id})
    except Exception as exc:  # the call never started, so it must not count against the job
        db.set_conversation_status(conversation_id, "blocked")
        reason = f"the call could not be placed: {type(exc).__name__}: {exc}"
        bus.publish(job_id, EventType.GUARDRAIL_BLOCKED, {"person_id": person.id, "reason": reason},
                    conversation_id)
        log.warning("Call to %s failed: %s", person.id, exc)
        return conversation_id, reason
    return conversation_id, None
