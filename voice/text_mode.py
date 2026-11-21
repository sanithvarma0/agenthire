"""Hold a conversation by typing, with no phone or audio.

The same instructions, status note, tools and state as a phone call, so most
behaviour can be tried and evaluated without dialling anyone. The evals
(evals/run.py) use `TextConversation` with a model playing the other person.

Interactive use, from the repository root:

    .venv\\Scripts\\python -m voice.text_mode --language te \\
        --work "the fan and a few switches in one room are not working" \\
        --area "Whitefields, HITEC City, Hyderabad" --when "tomorrow morning"

Type what the provider says; an empty line or Ctrl+C ends the conversation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from backend.models import ConversationRecord, EventType, FactSpec, Language
from backend.settings import Settings, get_settings
from voice.engine.kinds import build_record
from voice.engine.opening_check import check_opening
from voice.engine.prompt import CUES, build_instructions
from voice.engine.speech_text import (
    clean_for_speech,
    drop_repeated_question,
    in_wrong_script,
    is_unclear,
    keep_final_draft,
    normalise_transcript,
    strip_leaked_tool_text,
)
from voice.engine.state import ConversationState, Emit
from voice.engine.tools import call_tool, tool_specs

MAX_TOOL_ROUNDS = 5  # model calls per turn, so a looping model cannot stall a call
CLOSING_TURNS = 2    # agent turns allowed once there is nothing left to find out
CONNECTED_CUE = "The call has just connected. Say your first turn now."


def _ignore(_: EventType, __: dict[str, Any]) -> None:
    pass


def openai_client(settings: Settings) -> Any:
    from openai import OpenAI

    # Retries matter on the venue network, which drops connections at random.
    return OpenAI(api_key=settings.secrets.openai_api_key, timeout=30, max_retries=4)


class TextConversation:
    """One conversation driven turn by turn with text.

    `start()` returns the agent's opening; `reply(text)` takes what the other
    person said and returns the agent's answer, or None once the conversation
    has ended. Tool calls are run between model calls within a turn.
    """

    def __init__(self, record: ConversationRecord, *, settings: Settings | None = None, client: Any = None,
                 emit: Emit = _ignore, clock: Callable[[], float] = time.monotonic,
                 on_tool: Callable[[str, dict[str, Any], str], None] | None = None,
                 verify_opening: bool = True):
        self.settings = settings or get_settings()
        self.client = client or openai_client(self.settings)
        self.emit = emit
        self.on_tool = on_tool
        self.verify_opening = verify_opening
        self.state = ConversationState(record, emit=emit, clock=clock,
                                       gender_for=lambda language: self.settings.voice.gender_for(language.value))
        self.instructions = build_instructions(record, self.settings.voice.gender_for(record.language.value))
        self.tools = tool_specs(self.state)
        self.history: list[dict[str, Any]] = []
        self.last_agent_text = ""  # what the agent last said, to catch a repeated question
        self._pending_opening: dict[str, Any] | None = None
        self.unclear_turns = 0  # unclear lines in a row
        self.silent_turns = 0   # silences in a row
        self.turns_with_nothing_left = 0  # agent turns since there was nothing left to find out
        self._outcome_counted: Any = None  # the outcome those turns were counted for
        # Set by a runner that speaks as the reply streams (the voice worker): called with each
        # piece of the turn's first reply as the model writes it.
        self.on_text: Callable[[str], None] | None = None

    @property
    def ended(self) -> bool:
        return self.state.ended

    def start(self, *, announce: bool = True) -> str:
        """Prepare the opening, check it, and regenerate it once if it fails the check.

        On a phone call this runs while the phone is ringing, with `announce=False`;
        the worker calls `opening_spoken()` once the opening is actually said, so the
        transcript never shows an opening nobody heard.
        """
        self.emit(EventType.CONVERSATION_STARTED, {"kind": self.state.record.kind,
                                                   "language": self.state.record.language.value})
        started = time.perf_counter()
        history_before = len(self.history)
        text = self._turn({"role": "system", "content": CONNECTED_CUE}, announce=False)
        # The opening is checked only on the phone, where the ringing hides the time it takes.
        # In the browser the user is already waiting, and the check cost them about 5 s.
        if self.verify_opening and text and self.state.kind.channel == "phone":
            result = check_opening(text, self.state.record, self.state.kind,
                                   client=self.client, model=self.settings.secrets.llm_model_smart)
            retried = False
            if not result.ok:
                # Drop the failed opening and ask once more, saying what was wrong.
                del self.history[history_before:]
                self.last_agent_text = ""
                text = self._turn({"role": "system", "content": f"{CONNECTED_CUE} {result.feedback()}"},
                                  announce=False) or text
                retried = True
            self.emit(EventType.OPENING_CHECKED, {"missing": result.missing, "broken": result.broken,
                                                  "regenerated": retried})
        # The opening (and any regenerated draft) is not a reply: the next turn is the second.
        # Counting it put the second-turn reminder into the opening's own note on a real call.
        self.state.opened, self.state.replies = True, 0
        self._pending_opening = {"text": text, "response_ms": round((time.perf_counter() - started) * 1000)}
        if announce:
            self.opening_spoken()
        return text

    def opening_spoken(self) -> None:
        """Record the opening in the transcript, once it has actually been said."""
        if self._pending_opening and self._pending_opening["text"]:
            self.emit(EventType.AGENT_SAID, self._pending_opening)
        self._pending_opening = None

    def restart_clock(self) -> None:
        """Count the time cap from now, for example from when the phone was answered."""
        self.state.restart_clock()

    def reply(self, person_text: str) -> str | None:
        if self.ended:
            return None
        if self.state.seconds_elapsed >= self.state.record.time_cap_seconds:
            self._finish("time cap reached")
            return None
        person_text = normalise_transcript(person_text)
        self.state.person_said(person_text)
        self.emit(EventType.PERSON_SAID, {"text": person_text})
        self.silent_turns = 0
        if (is_unclear(person_text) or in_wrong_script(person_text)) and self.state.nothing_left_to_find:
            # Goodbyes are said: a mumble back (a "haa" once came back in Gujarati script) just
            # ends the call, as a silence does then, rather than asking them to repeat.
            self._finish("the conversation was finished")
            return None
        if is_unclear(person_text):
            # Could not be made out: ask once to repeat; after too many in a row, end politely.
            self.unclear_turns += 1
            if self.unclear_turns >= self.settings.turn_taking.unclear_turns_before_ending:
                self.state.closing_reason = "could not make out what they said"
                return self._turn({"role": "user", "content": person_text}, note=CUES["unclear_end"])
            return self._turn({"role": "user", "content": person_text}, note=CUES["unclear"])
        self.unclear_turns = 0
        # A line in the wrong script goes to the model with a note, not back as "please repeat":
        # on a real call "હા, કરું" (Hindi "haa, karu" in Gujarati script) was asked to be repeated.
        note = CUES["wrong_script"] if in_wrong_script(person_text) else None
        return self._turn({"role": "user", "content": person_text}, note=note)

    def on_silence(self) -> str | None:
        """The other person has gone quiet: check on them; after too many, end politely."""
        if self.ended:
            return None
        if self.state.nothing_left_to_find:
            # Goodbyes are said and nothing is left to ask: a silence just ends the call.
            self._finish("the conversation was finished")
            return None
        self.silent_turns += 1
        if self.silent_turns > self.settings.turn_taking.silence_prompts_before_ending:
            self.state.closing_reason = "the line went quiet"
            return self._turn({"role": "system", "content": CUES["silent_end"]})
        return self._turn({"role": "system", "content": CUES["silent"]})

    def keep_going(self) -> str | None:
        """The agent finished a turn without asking anything and nobody spoke: carry on.
        On a real call this dead air made the builder hang up."""
        if self.ended or self.state.nothing_left_to_find:
            return None
        return self._turn({"role": "system", "content": CUES["keep_going"]})

    def wrap_up(self) -> str | None:
        """Time is nearly up and nothing is being said: tell the agent to close."""
        if self.ended:
            return None
        return self._turn({"role": "system", "content": CUES["wrap_up"]})

    def close(self, reason: str) -> None:
        """End from outside, for example when the other person hangs up."""
        if not self.ended:
            self._finish(reason)

    # --- internals ----------------------------------------------------------

    def _turn(self, incoming: dict[str, Any], *, announce: bool = True, note: str | None = None) -> str:
        status = {"role": "system", "content": self.state.status() + (f"\n{note}" if note else "")}
        turn: list[dict[str, Any]] = [incoming]
        spoken: list[str] = []
        started = time.perf_counter()
        for _ in range(MAX_TOOL_ROUNDS):
            # The status note goes right after the person's latest line, where the
            # model weighs it most (a language switch was missed when it came before).
            message = self._complete([{"role": "system", "content": self.instructions},
                                      *self.history, turn[0], status, *turn[1:]],
                                     on_text=self.on_text if announce and not spoken else None)
            content = clean_for_speech(keep_final_draft(strip_leaked_tool_text(message.content or "")))
            # Only the first thing the model says in a turn is spoken. Asked again
            # after its tool calls, it tends to repeat itself.
            if content and not spoken:
                spoken.append(content)
            calls = message.tool_calls or []
            turn.append(_assistant_message(content, calls))
            if not calls:
                break
            refused = False
            for call in calls:
                result = call_tool(self.state, call.function.name, call.function.arguments)
                refused = refused or result.startswith("Refused")
                if self.on_tool:
                    self.on_tool(call.function.name, _parse(call.function.arguments), result)
                turn.append({"role": "tool", "tool_call_id": call.id, "content": result})
            if self.state.ended:
                break
            # Ask the model again only if it has not spoken yet, or a tool call
            # was refused and it may need to correct itself.
            if spoken and not refused:
                break
        self.history.extend(turn)

        text = drop_repeated_question(" ".join(spoken), self.last_agent_text)
        if text:
            self.last_agent_text = text
        if self.state.outcome != self._outcome_counted:
            self._outcome_counted, self.turns_with_nothing_left = self.state.outcome, 0
        if self.state.nothing_left_to_find and "set_outcome" in self.state.kind.tools:
            # Once there is nothing left to find out, allow a short goodbye, then hang up.
            # In an eval run the agent and the provider said goodbye to each other for
            # ten turns because the model never ended the call.
            self.turns_with_nothing_left += 1
            if self.turns_with_nothing_left >= CLOSING_TURNS and not self.state.closing_reason:
                self.state.closing_reason = "the conversation was finished"
        if text and announce:
            self.emit(EventType.AGENT_SAID, {"text": text,
                                             "response_ms": round((time.perf_counter() - started) * 1000)})
        self.state.after_agent_reply()
        if self.state.ended:
            self._finish(self.state.end_reason or "ended")
        return text

    def _complete(self, messages: list[dict[str, Any]], on_text: Callable[[str], None] | None = None) -> Any:
        """One model call, streamed: the larger model, thinking a little (config.yaml,
        voice.reasoning_effort), through the Responses API, which is what lets it think and
        use tools together. The history stays as chat messages and is converted here.
        Returns a message with `content` and `tool_calls`, as before."""
        instructions, items = to_responses_input(messages)
        stream = self.client.responses.create(
            model=self.settings.secrets.llm_model_smart,
            instructions=instructions,
            input=items,
            tools=[{"type": "function", **spec["function"]} for spec in self.tools],
            parallel_tool_calls=False,
            reasoning={"effort": self.settings.voice.reasoning_effort},
            stream=True,
            store=False,
        )
        text, output, speaking = [], [], None
        for event in stream:
            if event.type == "response.output_text.delta":
                # Only the first message that has words is spoken. The larger model may send a
                # second message in the same reply (a "commentary" then a "final answer"), and
                # once it repeated the first word for word, so a greeting was said twice.
                item = getattr(event, "item_id", None)
                speaking = item if speaking is None else speaking
                if item != speaking:
                    continue
                text.append(event.delta)
                if on_text:
                    on_text(event.delta)
            elif event.type == "response.completed":
                output = list(event.response.output or [])
        calls = [SimpleCall(item.call_id, item.name, item.arguments) for item in output
                 if getattr(item, "type", "") == "function_call"]
        return SimpleNamespace(content="".join(text) or None, tool_calls=calls or None)

    def _finish(self, reason: str) -> None:
        if not self.state.ended:
            self.state.end(reason)
        self.emit(EventType.CONVERSATION_ENDED, {"reason": self.state.end_reason})


class SimpleCall:
    """A tool call in the shape the turn loop reads (id, function.name, function.arguments)."""

    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=arguments)


def to_responses_input(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Chat messages as Responses API input: the first system message becomes the
    instructions, later ones developer notes; tool calls and results become items."""
    instructions, items = "", []
    for i, m in enumerate(messages):
        role = m["role"]
        if role == "system" and i == 0:
            instructions = m["content"]
        elif role == "system":
            items.append({"role": "developer", "content": m["content"]})
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": m["tool_call_id"], "output": m["content"]})
        elif role == "assistant":
            if m.get("content"):
                items.append({"role": "assistant", "content": m["content"]})
            for call in m.get("tool_calls") or []:
                items.append({"type": "function_call", "call_id": call["id"], "name": call["function"]["name"],
                              "arguments": call["function"]["arguments"]})
        else:
            items.append({"role": role, "content": m["content"]})
    return instructions, items


def _parse(arguments: str) -> dict[str, Any]:
    try:
        return json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {}


def _assistant_message(content: str | None, calls: list[Any]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function",
             "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in calls
        ]
    return message


# --- command line -----------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Hold an AgentHire conversation by typing.")
    parser.add_argument("--kind", default="home_call")
    parser.add_argument("--language", default="te", choices=[lang.value for lang in Language])
    parser.add_argument("--calling", default="", help="The business or person to ask for (home calls)")
    parser.add_argument("--work", default="", help="What needs doing (home calls)")
    parser.add_argument("--area", required=True, help="Colony, locality and city")
    parser.add_argument("--when", default="", help="When the visit is wanted")
    parser.add_argument("--budget", default="")
    parser.add_argument("--question", action="append", default=[], help="An extra question for this job")
    args = parser.parse_args(argv)

    settings = get_settings()
    shareable = {"calling": args.calling} if args.calling else {}
    shareable |= ({"work": args.work} if args.work else {}) | {"area": args.area}
    if args.when:
        shareable["wanted"] = args.when
    if args.budget:
        shareable["budget"] = args.budget
    extra = [FactSpec(name=f"question_{i + 1}", description=q, required=False)
             for i, q in enumerate(args.question)]
    record = build_record(args.kind, Language(args.language),
                          time_cap_seconds=settings.calling.time_cap_seconds,
                          wrap_up_at_seconds=settings.calling.wrap_up_at_seconds,
                          shareable=shareable, extra_facts=extra)

    def show_tool(name: str, arguments: dict[str, Any], result: str) -> None:
        print(f"    [{name} {json.dumps(arguments, ensure_ascii=False)} -> {result}]", flush=True)

    conversation = TextConversation(record, settings=settings, on_tool=show_tool)
    print(f"AGENT:  {conversation.start()}", flush=True)
    try:
        while not conversation.ended:
            line = input("YOU:    ").strip()
            if not line:
                conversation.close("ended by the tester")
                break
            answer = conversation.reply(line)
            if answer:
                print(f"AGENT:  {answer}", flush=True)
    except (KeyboardInterrupt, EOFError):
        conversation.close("ended by the tester")

    state = conversation.state
    print("\n--- result")
    print(f"ended:    {state.end_reason}")
    print(f"outcome:  {state.outcome.value if state.outcome else 'not set'}")
    print(f"do not call: {state.do_not_call}")
    for fact in state.facts.values():
        print(f"fact:     {fact.name} = {fact.value}   (said: {fact.said_as})")
    if state.missing_required:
        print(f"missing:  {', '.join(state.missing_required)}")


if __name__ == "__main__":
    main()
