"""The live state of one conversation: what has been found out, how it ended, and the time.

The state belongs to the voice worker (or the text-mode runner) for the length of
one conversation. It knows nothing about LiveKit or the database: changes are
reported through an `emit` callback, which the caller connects to the event stream.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from backend.models import SETTLED, TAKING_PART, CallResult, CollectedFact, ConversationRecord, EventType, Language, Outcome
from backend.text_match import quote_in_line
from voice.engine.speech_text import indian_script, words_in_script
from voice.engine.kinds import Kind, get_kind
from voice.engine.prompt import status_note

# Words in another language's script needed for one line to switch the reply language.
SWITCH_MIN_WORDS = 3

Emit = Callable[[EventType, dict[str, Any]], None]


def _ignore(_: EventType, __: dict[str, Any]) -> None:
    pass




class ConversationState:
    def __init__(self, record: ConversationRecord, *, kind: Kind | None = None, emit: Emit = _ignore,
                 clock: Callable[[], float] = time.monotonic,
                 gender_for: Callable[[Language], str] | None = None):
        self.record = record
        # The gender of the voice for each language, so word forms follow a voice change.
        self.gender_for = gender_for
        self.kind = kind or get_kind(record.kind)
        self.emit = emit
        self._clock = clock
        self._started = clock()
        self.facts: dict[str, CollectedFact] = {}
        self.person_lines: list[str] = []  # everything the other person has said, in order
        # The language the agent should reply in. Starts as the call's language and
        # follows the other person if they speak another Indian language.
        self.reply_language: Language = record.language
        self.outcome: Outcome | None = None
        self.do_not_call = False
        self.ended = False
        self.end_reason: str | None = None
        # Set when the conversation must end after the agent's next reply, whatever
        # the model does then (for example after a request not to be called again).
        self.closing_reason: str | None = None
        self.opened = False  # set by the runner once the opening is ready
        self.replies = 0     # the agent's replies after its opening

    # --- reading ------------------------------------------------------------

    @property
    def seconds_elapsed(self) -> float:
        return self._clock() - self._started

    @property
    def fact_names(self) -> list[str]:
        return [f.name for f in self.record.facts_to_collect]

    @property
    def missing_required(self) -> list[str]:
        return [f.name for f in self.record.facts_to_collect if f.required and f.name not in self.facts]

    def status(self) -> str:
        """The per-turn note for the model: what is still missing and the time left."""
        switched = self.reply_language != self.record.language
        gender = self.gender_for(self.reply_language) if switched and self.gender_for else None
        return status_note(self.record, self.facts.keys(), self.seconds_elapsed, self.reply_language, gender,
                           replies_so_far=self.replies if self.opened else None)

    def live_result(self) -> CallResult | None:
        """What the agent recorded during the call. The result shown to the user is
        built afterwards from the transcript (task 1.6); this one is a cross-check."""
        if self.outcome is None:
            return None
        return CallResult(outcome=self.outcome, facts=list(self.facts.values()), do_not_call=self.do_not_call)

    def was_said(self, quote: str) -> bool:
        """Whether the quoted words come from something the other person said.

        A fact must be backed by their words. Most of the quoted words have to
        appear in a single thing they said, so a model cannot record a fact
        nobody stated. It does not judge meaning: that is the transcript check's job.
        """
        return any(quote_in_line(quote, line) for line in self.person_lines)

    # --- changing -----------------------------------------------------------

    def person_said(self, text: str) -> None:
        """The runner reports each final transcript of the other person's speech."""
        if text.strip():
            previous = self.person_lines[-1] if self.person_lines else ""
            self.person_lines.append(text.strip())
            spoken = indian_script(text)
            if spoken and spoken != self.reply_language.value and self.kind.follow_language:
                # A short line is not enough to switch: on real calls, line noise came back
                # as a one-word Hindi "no", and Telugu speech once came back as three words
                # with two in Hindi script. A real short reply ("haan ji, ... boliye") has
                # three. Switch on SWITCH_MIN_WORDS words in the new script, or on two lines
                # in a row in it.
                if words_in_script(text, spoken) >= SWITCH_MIN_WORDS or indian_script(previous) == spoken:
                    self.reply_language = Language(spoken)
                    self.emit(EventType.LANGUAGE_CHANGED, {"language": spoken})

    def record_fact(self, name: str, value: str, said_as: str) -> CollectedFact:
        fact = CollectedFact(name=name, value=value, said_as=said_as)
        self.facts[name] = fact  # a later answer replaces an earlier one, as when someone corrects themselves
        self.emit(EventType.FACT_RECORDED, fact.model_dump(include={"name", "value", "said_as"}))
        return fact

    def set_outcome(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.emit(EventType.OUTCOME_SET, {"outcome": outcome.value})

    def mark_do_not_call(self) -> None:
        self.do_not_call = True
        if self.outcome is None:
            self.set_outcome(Outcome.DECLINED)
        self.closing_reason = "asked not to be called again"

    def end(self, reason: str) -> None:
        self.ended = True
        self.end_reason = reason

    @property
    def nothing_left_to_find(self) -> bool:
        """The enquiry is settled: they cannot or will not take the job, or they can
        and every required fact is found. `call_customer` does not count: the model
        has set it too early while the provider was still asking about the job."""
        if self.outcome in SETTLED:
            return True
        return self.outcome in TAKING_PART and not self.missing_required

    def restart_clock(self) -> None:
        """Count the time cap from now (on a phone call, from when it is answered)."""
        self._started = self._clock()

    def after_agent_reply(self) -> None:
        """Called by the runner once the agent's reply has been spoken. Ends the
        conversation if it was due to close, even if the model forgot to."""
        self.replies += 1
        if self.closing_reason and not self.ended:
            self.end(self.closing_reason)
