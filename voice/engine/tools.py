"""The four tools the agent can call during a conversation (docs/LLD.md, section 9).

`tool_specs` gives the model the tools its conversation kind allows, as JSON
schemas. `call_tool` runs one call against the conversation state and returns a
short message for the model. Bad calls are refused with a message saying why,
so the model can correct itself; they never change the state.
"""

from __future__ import annotations

import json
from typing import Any

from backend.models import TAKING_PART, EventType, Outcome, outcome_meanings
from voice.engine.state import ConversationState


def tool_specs(state: ConversationState) -> list[dict[str, Any]]:
    """OpenAI-style function definitions for the tools this conversation allows."""
    meanings = outcome_meanings(state.kind.name)
    specs = {
        "record_fact": {
            "description": "Record something the other person told you that you were asked to find out.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": state.fact_names,
                             "description": "Which fact this is"},
                    "value": {"type": "string",
                              "description": "The value in a plain normalised form, for example 300 for "
                                             "three hundred rupees, or a day and a time"},
                    "said_as": {"type": "string", "description": "The other person's own words"},
                },
                "required": ["name", "value", "said_as"],
                "additionalProperties": False,
            },
        },
        "set_outcome": {
            "description": "Record how this conversation has turned out. "
                           + "; ".join(f"{o.value}: {meaning}" for o, meaning in meanings.items()),
            "parameters": {
                "type": "object",
                "properties": {"outcome": {"type": "string", "enum": [o.value for o in meanings]}},
                "required": ["outcome"],
                "additionalProperties": False,
            },
        },
        "mark_do_not_call": {
            "description": "Use only when they ask not to be called again.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        "end_conversation": {
            "description": "End the conversation, after you have said a short goodbye.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string", "description": "Why the conversation is ending"}},
                "required": ["reason"],
                "additionalProperties": False,
            },
        },
    }
    return [
        {"type": "function", "function": {"name": name, "strict": True, **specs[name]}}
        for name in state.kind.tools
    ]


def call_tool(state: ConversationState, name: str, arguments: dict[str, Any] | str) -> str:
    """Run one tool call and return the message for the model.

    Every call, accepted or refused, is reported as a `tool_called` event.
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    result = _run(state, name, arguments)
    state.emit(EventType.TOOL_CALLED, {"name": name, "arguments": arguments, "result": result})
    return result


def _run(state: ConversationState, name: str, args: dict[str, Any]) -> str:
    if state.ended:
        return "Refused: the conversation has already ended."
    if name not in state.kind.tools:
        return f"Refused: {name} is not available in this conversation."

    if name == "record_fact":
        fact_name = str(args.get("name", ""))
        value, said_as = str(args.get("value", "")).strip(), str(args.get("said_as", "")).strip()
        if fact_name not in state.fact_names:
            return f"Refused: unknown fact {fact_name!r}. Facts to find out: {', '.join(state.fact_names)}."
        if not value or not said_as:
            return "Refused: give both the value and the other person's own words."
        if not state.was_said(said_as):
            return ("Refused: the other person has not said that. Record a fact only from their own words, "
                    "after they have clearly answered.")
        state.record_fact(fact_name, value, said_as)
        missing = state.missing_required
        return f"Recorded {fact_name}. " + (
            f"Still to find out: {', '.join(missing)}." if missing else "All required facts are found.")

    if name == "set_outcome":
        try:
            outcome = Outcome(str(args.get("outcome", "")))
        except ValueError:
            outcome = None
        meanings = outcome_meanings(state.kind.name)
        if outcome not in meanings:
            return f"Refused: outcome must be one of {', '.join(o.value for o in meanings)}."
        state.set_outcome(outcome)
        return f"Outcome set to {outcome.value}."

    if name == "mark_do_not_call":
        state.mark_do_not_call()
        return ("Noted: this number will not be called again. Apologise briefly in one sentence; "
                "the call ends right after that.")

    if name == "end_conversation":
        if "set_outcome" in state.kind.tools and state.outcome is None:
            return "Refused: call set_outcome first, so the result of this conversation is known."
        if _must_keep_asking(state):
            return (f"Refused: they are taking part, but you still need: {', '.join(state.missing_required)}. "
                    f"Ask about it now, then end.")
        state.end(str(args.get("reason", "")).strip() or "not given")
        return "Ending the conversation."

    return f"Refused: {name} is not a known tool."


def _must_keep_asking(state: ConversationState) -> bool:
    """A provider who can take the job (or a candidate who is interested) must be asked
    for every required fact before the call ends (an eval run hung up after the time,
    without asking the charge). Once it is time to wrap up, ending is allowed with
    whatever was found."""
    if state.outcome not in TAKING_PART or not state.missing_required:
        return False
    wrap_up_at = state.record.wrap_up_at_seconds
    return wrap_up_at is None or state.seconds_elapsed < wrap_up_at
