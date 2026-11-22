"""Tests for the text-mode runner, using a fake model so nothing goes over the network."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from backend.models import EventType, Language, Outcome
from backend.settings import load_settings
from voice.engine.kinds import build_record
from voice.text_mode import TextConversation


def message(content: str | None = None, *calls: tuple[str, dict]) -> SimpleNamespace:
    tool_calls = [
        SimpleNamespace(id=f"call_{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        for i, (name, args) in enumerate(calls)
    ]
    return SimpleNamespace(content=content, tool_calls=tool_calls or None)


class FakeModel:
    """Returns the scripted messages in order and keeps every request it was sent.

    Conversations use the Responses API, streamed; the opening check uses chat completions.
    Each request is kept with a chat-style `messages` view, so tests read both the same way."""

    def __init__(self, *replies: SimpleNamespace):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.responses = SimpleNamespace(create=self._responses)

    def _chat(self, **kwargs) -> SimpleNamespace:
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=self.replies.pop(0))])

    def _responses(self, **kwargs):
        self.requests.append({**kwargs, "messages": as_chat(kwargs["instructions"], kwargs["input"])})
        reply = self.replies.pop(0)
        events = [SimpleNamespace(type="response.output_text.delta", delta=reply.content)] if reply.content else []
        output = [SimpleNamespace(type="function_call", call_id=c.id, name=c.function.name,
                                  arguments=c.function.arguments) for c in reply.tool_calls or []]
        return iter([*events, SimpleNamespace(type="response.completed", response=SimpleNamespace(output=output))])


def as_chat(instructions: str, items: list[dict]) -> list[dict]:
    """A Responses request read back as chat messages, for assertions."""
    out = [{"role": "system", "content": instructions}]
    for item in items:
        if item.get("type") == "function_call_output":
            out.append({"role": "tool", "content": item["output"]})
        elif item.get("type") == "function_call":
            out.append({"role": "assistant", "content": "", "tool_call": item["name"]})
        else:
            out.append({"role": "system" if item["role"] == "developer" else item["role"], "content": item["content"]})
    return out


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def conversation(model: FakeModel, clock: FakeClock | None = None, verify_opening: bool = False):
    events: list[tuple[EventType, dict]] = []
    record = build_record("home_call", Language.TELUGU, time_cap_seconds=180, wrap_up_at_seconds=150,
                          shareable={"work": "a fan is not working", "area": "Madhapur"})
    convo = TextConversation(record, settings=load_settings(), client=model,
                             emit=lambda t, p: events.append((t, p)), clock=clock or FakeClock(),
                             verify_opening=verify_opening)
    return convo, events


def check_reply(missing=(), broken=()) -> SimpleNamespace:
    return message(json.dumps({"missing": list(missing), "broken": list(broken)}))


def types(events) -> list[EventType]:
    return [t for t, _ in events]


def test_opening_uses_the_instructions_and_status() -> None:
    model = FakeModel(message("అన్నా నమస్తే"))
    convo, events = conversation(model)
    assert convo.start() == "అన్నా నమస్తే"
    sent = model.requests[0]
    assert sent["messages"][0]["role"] == "system" and "# Goal" in sent["messages"][0]["content"]
    assert "Still to find out" in sent["messages"][-1]["content"]
    assert sent["parallel_tool_calls"] is False and sent["reasoning"] == {"effort": "low"}
    assert sent["model"] == load_settings().secrets.llm_model_smart and sent["stream"] is True
    assert [t["name"] for t in sent["tools"]][0] == "record_fact"
    assert types(events) == [EventType.CONVERSATION_STARTED, EventType.AGENT_SAID]


def test_a_turn_runs_tools_then_speaks() -> None:
    model = FakeModel(
        message("అన్నా నమస్తే"),
        message(None, ("record_fact", {"name": "visiting_charge", "value": "300", "said_as": "మూడు వందలు"})),
        message("సరే అన్నా, మూడు వందలు."),
    )
    convo, events = conversation(model)
    convo.start()
    assert convo.reply("మూడు వందలు అన్నా") == "సరే అన్నా, మూడు వందలు."
    assert convo.state.facts["visiting_charge"].value == "300"
    assert types(events)[2:] == [EventType.PERSON_SAID, EventType.FACT_RECORDED, EventType.TOOL_CALLED,
                                 EventType.AGENT_SAID]
    # The tool result went back to the model in the same turn.
    last = model.requests[-1]["messages"]
    assert last[-1]["role"] == "tool" and last[-1]["content"].startswith("Recorded visiting_charge")


def test_history_carries_across_turns_but_status_is_fresh() -> None:
    model = FakeModel(message("opening"), message("first answer"), message("second answer"))
    convo, _ = conversation(model)
    convo.start()
    convo.reply("one")
    convo.reply("two")
    sent = model.requests[-1]["messages"]
    contents = [m["content"] for m in sent]
    assert "one" in contents and "first answer" in contents
    assert contents[-2] == "two" and contents[-1].startswith("Status for you only")  # note after the latest line
    assert sum("Status for you only" in c for c in contents) == 1  # old notes are not resent


def test_ending_stops_further_turns() -> None:
    model = FakeModel(
        message("opening"),
        message("bye", ("set_outcome", {"outcome": "not_available"}), ("end_conversation", {"reason": "busy"})),
    )
    convo, events = conversation(model)
    convo.start()
    assert convo.reply("busy this week") == "bye"
    assert convo.ended and convo.state.outcome is Outcome.NOT_AVAILABLE
    assert convo.reply("hello?") is None
    assert types(events)[-1] == EventType.CONVERSATION_ENDED


def test_do_not_call_ends_after_the_apology() -> None:
    model = FakeModel(message("opening"), message(None, ("mark_do_not_call", {})), message("sorry"))
    convo, _ = conversation(model)
    convo.start()
    assert convo.reply("don't call me again") == "sorry"
    assert convo.ended and convo.state.do_not_call


def test_time_cap_ends_the_conversation() -> None:
    clock = FakeClock()
    model = FakeModel(message("opening"))
    convo, events = conversation(model, clock)
    convo.start()
    clock.now = 181
    assert convo.reply("still there?") is None
    assert convo.ended and convo.state.end_reason == "time cap reached"
    assert len(model.requests) == 1


def test_speaking_with_a_tool_call_ends_the_turn_without_a_repeat() -> None:
    model = FakeModel(
        message("opening"),
        message("సరే అన్నా, charge ఎంత?",
                ("record_fact", {"name": "earliest_time", "value": "2026-11-22 11:00", "said_as": "రేపు 11కి"})),
        message("charge ఎంత అన్నా?"),  # the repeat that must not be asked for or spoken
    )
    convo, _ = conversation(model)
    convo.start()
    assert convo.reply("రేపు 11కి వస్తా") == "సరే అన్నా, charge ఎంత?"
    assert len(model.requests) == 2


def test_after_a_refused_tool_the_model_is_asked_again_but_not_heard_twice() -> None:
    model = FakeModel(
        message("opening"),
        message("సరే అన్నా, bye", ("end_conversation", {"reason": "done"})),  # refused: no outcome yet
        message("bye అన్నా", ("set_outcome", {"outcome": "not_available"}), ("end_conversation", {"reason": "done"})),
    )
    convo, _ = conversation(model)
    convo.start()
    assert convo.reply("ok") == "సరే అన్నా, bye"
    assert convo.ended and len(model.requests) == 3


def test_unspeakable_characters_are_removed() -> None:
    stray = chr(0x660E)  # a Chinese character, as seen once in an eval run
    model = FakeModel(message(stray + "ుదు, tomorrow 11 అంటే?"))
    convo, _ = conversation(model)
    assert convo.start() == "ుదు, tomorrow 11 అంటే?"


def test_telugu_transcribed_in_kannada_script_is_put_back_in_telugu() -> None:
    model = FakeModel(message("opening"), message("సరే అన్నా"))
    convo, events = conversation(model)
    convo.start()
    kannada = "".join(chr(c) for c in (0x0CB9, 0x0CBE, 0x0020, 0x0C86, 0x0CAF, 0x0CCD, 0x0CA4, 0x0CC1))
    convo.reply(kannada)
    said = next(p["text"] for t, p in events if t == EventType.PERSON_SAID)
    assert said == "".join(chr(c) for c in (0x0C39, 0x0C3E, 0x0020, 0x0C06, 0x0C2F, 0x0C4D, 0x0C24, 0x0C41))
    assert convo.state.person_lines == [said]


def test_a_question_repeated_from_the_last_turn_is_dropped() -> None:
    # The pattern from the first real call.
    model = FakeModel(
        message("అన్నా నమస్తే, మా ఇంట్లో fan పని చేయట్లేదు. మీరు వచ్చి చూసి చెయ్యగలరా?"),
        message("ఒక switchboard నుంచి చిన్న sparks వస్తున్నాయి అన్నా. మీరు వచ్చి చూసి చెయ్యగలరా?"),
        message("మీరు వచ్చి చూసి చెయ్యగలరా?"),
    )
    convo, _ = conversation(model)
    convo.start()
    assert convo.reply("switchboard లో ఏమొస్తున్నాయి?") == "ఒక switchboard నుంచి చిన్న sparks వస్తున్నాయి అన్నా."
    # A reply that is only the question is kept, since there is nothing else to say.
    assert convo.reply("...") == "మీరు వచ్చి చూసి చెయ్యగలరా?"


def test_a_repeat_on_request_keeps_its_question() -> None:
    # From a real call: asked to repeat, the agent's question was dropped and both sides waited.
    opening = ("అన్నా హలో, కండాపూర్ దగ్గర మా ఇంట్లో ఒక చిన్న problem ఉంది, bedroom లో fan, రెండు lights పని "
               "చేయట్లేదు. మీరు వచ్చి ఒకసారి చూసి చెప్పగలరా?")
    repeat = "అన్నా, కండాపూర్ లో మా ఇంట్లో bedroom fan, రెండు lights పని చేయట్లేదు. మీరు వచ్చి ఒకసారి చూసి చెప్పగలరా?"
    model = FakeModel(message(opening), message(repeat))
    convo, _ = conversation(model)
    convo.start()
    assert convo.reply("అర్థం కాలేదు ఒకసారి మళ్ళీ చెప్తారా?") == repeat


def test_dead_air_makes_the_agent_carry_on() -> None:
    model = FakeModel(message("opening"), message("సరే అన్నా."), message("ఎప్పుడు రావచ్చు అన్నా?"))
    convo, _ = conversation(model)
    convo.start()
    convo.reply("వస్తాను")
    assert convo.keep_going() == "ఎప్పుడు రావచ్చు అన్నా?"
    assert "waiting for you to go on" in model.requests[-1]["messages"][-2]["content"]
    assert convo.silent_turns == 0  # carrying on is not counted as a silence check


def test_no_carrying_on_once_the_call_is_settled() -> None:
    model = FakeModel(message("opening"), message("సరే అండి.", ("set_outcome", {"outcome": "not_available"})))
    convo, _ = conversation(model)
    convo.start()
    convo.reply("busy అండి")
    assert convo.keep_going() is None


def test_a_different_question_is_kept() -> None:
    model = FakeModel(
        message("అన్నా నమస్తే. మీరు వచ్చి చూసి చెయ్యగలరా?"),
        message("సరే అన్నా, రేపు పది గంటలకి. Visiting charge ఎంత అవుతుంది?"),
    )
    convo, _ = conversation(model)
    convo.start()
    assert convo.reply("రేపు పది గంటలకి వస్తా") == "సరే అన్నా, రేపు పది గంటలకి. Visiting charge ఎంత అవుతుంది?"


def test_a_tool_call_written_into_the_reply_is_never_spoken() -> None:
    # The exact reply from a real call, where the model wrote its tool call as text.
    leaked = ('"name":"available","value":"yes","said as":"అవును, చూసి చేయగలం." \n'
              "అవును, చూసి చేయగలం. రేపు లేదా ఇవాళ ఎప్పుడు వచ్చేయగలరో చెప్తారా?")
    model = FakeModel(message("opening"), message(leaked))
    convo, _ = conversation(model)
    convo.start()
    spoken = convo.reply("బాత్రూమ్ గీజర్ ఏమైంది?")
    assert spoken == "అవును, చూసి చేయగలం. రేపు లేదా ఇవాళ ఎప్పుడు వచ్చేయగలరో చెప్తారా?"
    assert '"' not in spoken and "available" not in spoken


def test_a_good_opening_is_checked_once_and_kept() -> None:
    model = FakeModel(message("అన్నా నమస్తే, మాదాపూర్ లో మా ఇంట్లో fan పని చేయట్లేదు, వచ్చి చూస్తారా?"), check_reply())
    convo, events = conversation(model, verify_opening=True)
    assert convo.start().startswith("అన్నా నమస్తే")
    assert len(model.requests) == 2
    checked = next(p for t, p in events if t == EventType.OPENING_CHECKED)
    assert checked == {"missing": [], "broken": [], "regenerated": False}


def test_a_failed_opening_is_regenerated_with_what_was_wrong() -> None:
    must_not = "say that it is an AI or an assistant"
    model = FakeModel(message("నేను AI assistant ని, fan పని చేయట్లేదు."),
                      check_reply(broken=[1]),  # the check answers by item number
                      message("అన్నా నమస్తే, మాదాపూర్ లో fan పని చేయట్లేదు, వచ్చి చూస్తారా?"))
    convo, events = conversation(model, verify_opening=True)
    assert convo.start() == "అన్నా నమస్తే, మాదాపూర్ లో fan పని చేయట్లేదు, వచ్చి చూస్తారా?"
    regenerate = model.requests[2]["messages"]
    assert any(f"Your opening must not: {must_not}." in m["content"] for m in regenerate if m["role"] == "system")
    assert not any("నేను AI assistant ని" in (m.get("content") or "") for m in regenerate)  # failed opening dropped
    assert next(p for t, p in events if t == EventType.OPENING_CHECKED)["regenerated"] is True


def test_the_second_turn_reminder_goes_to_the_second_turn_not_the_opening() -> None:
    # On a real call the opening was counted as a reply, so the reminder to name the
    # area and the problem reached the opening, and the opening check rejected it.
    reminder = "This is your second turn"

    def notes(request) -> str:
        return " ".join(m["content"] for m in request["messages"] if m["role"] == "system" and m.get("content"))

    model = FakeModel(message("అన్నా నమస్తే, Sri Sai Electricals ఆ?"), check_reply(),
                      message("మాదాపూర్ నుంచి, fan పని చేయట్లేదు, వచ్చి చూస్తారా?"),
                      message("ఎప్పుడు రావచ్చు అన్నా?"))
    convo, _ = conversation(model, verify_opening=True)
    convo.start()
    assert reminder not in notes(model.requests[0])
    convo.reply("అవునండి, చెప్పండి.")
    assert reminder in notes(model.requests[2])
    convo.reply("సరే, చూస్తా.")
    assert reminder not in notes(model.requests[3])


def test_check_results_outside_the_lists_are_ignored() -> None:
    model = FakeModel(message("అన్నా నమస్తే"), check_reply(missing=[99, 0]))
    convo, events = conversation(model, verify_opening=True)
    convo.start()
    assert len(model.requests) == 2  # nothing real was missing, so no regeneration


def test_an_opening_prepared_during_ringing_is_not_in_the_transcript_until_spoken() -> None:
    model = FakeModel(message("అన్నా నమస్తే"))
    convo, events = conversation(model)
    convo.start(announce=False)
    assert EventType.AGENT_SAID not in types(events)
    convo.opening_spoken()
    assert [p["text"] for t, p in events if t == EventType.AGENT_SAID] == ["అన్నా నమస్తే"]
    convo.opening_spoken()  # only once
    assert len([t for t, _ in events if t == EventType.AGENT_SAID]) == 1


def test_the_time_cap_counts_from_the_answer() -> None:
    clock = FakeClock()
    model = FakeModel(message("opening"), message("reply"))
    convo, _ = conversation(model, clock)
    convo.start(announce=False)
    clock.now = 60          # a minute of ringing
    convo.restart_clock()   # answered
    clock.now = 60 + 170    # 170 s into the call: still under the 180 s cap
    assert convo.reply("hello") == "reply"


def test_a_draft_followed_by_its_rewrite_is_spoken_once() -> None:
    # The exact reply from an eval run.
    drafted = ("అన్నా, మీరు ఎప్పుడు రావచ్చు? Might say tomorrow if possible.\n"
               "అన్నా, మీరు ఎప్పుడు రావచ్చు? tomorrow అయితే ఎప్పుడు?")
    model = FakeModel(message("opening"), message(drafted))
    convo, _ = conversation(model)
    convo.start()
    assert convo.reply("అవును, వచ్చి చూసేస్తాను.") == "అన్నా, మీరు ఎప్పుడు రావచ్చు? tomorrow అయితే ఎప్పుడు?"


def test_two_different_paragraphs_are_both_kept() -> None:
    two = "సరే అన్నా, రేపు 11కి.\nVisiting charge ఎంత అవుతుంది?"
    model = FakeModel(message("opening"), message(two))
    convo, _ = conversation(model)
    convo.start()
    assert convo.reply("రేపు 11కి వస్తా") == "సరే అన్నా, రేపు 11కి.\nVisiting charge ఎంత అవుతుంది?"


def test_unclear_speech_gets_a_request_to_repeat_then_a_polite_end() -> None:
    model = FakeModel(message("opening"), message("అన్నా, మళ్లీ చెప్తారా?"), message("లైన్ సరిగా లేదు అన్నా, మళ్లీ కాల్ చేస్తా."))
    convo, events = conversation(model)
    convo.start()
    assert convo.reply("...") == "అన్నా, మళ్లీ చెప్తారా?"  # nothing with letters came back
    assert "could not be made out" in model.requests[-1]["messages"][-1]["content"]
    assert not convo.ended
    convo.reply("...")
    assert "still cannot make out" in model.requests[-1]["messages"][-1]["content"]
    assert convo.ended and convo.state.end_reason == "could not make out what they said"


def test_a_line_in_the_wrong_script_goes_to_the_model_with_a_note() -> None:
    # From a real call: Hindi "haa, karu" came back in Gujarati script and was treated as
    # unclear, so the agent asked to repeat a plain yes.
    model = FakeModel(message("opening"), message("ठीक है भैया."))
    convo, _ = conversation(model)
    convo.start()
    gujarati = chr(0x0AB9) + chr(0x0ABE) + ", " + chr(0x0A95) + chr(0x0AB0) + chr(0x0AC1) + "."
    assert convo.reply(gujarati) == "ठीक है भैया."
    sent = model.requests[-1]["messages"]
    assert sent[-2]["content"] == gujarati and "probably their speech written in the wrong script" in sent[-1]["content"]
    assert convo.unclear_turns == 0


def test_clear_speech_resets_the_unclear_count() -> None:
    model = FakeModel(message("opening"), message("repeat?"), message("ok"), message("repeat again?"))
    convo, _ = conversation(model)
    convo.start()
    convo.reply("...")
    convo.reply("హా అన్నా")  # clear
    convo.reply("...")
    assert not convo.ended  # two unclear lines, but not in a row


def test_a_one_letter_acknowledgement_is_clear() -> None:
    model = FakeModel(message("opening"), message("సరే"))
    convo, _ = conversation(model)
    convo.start()
    convo.reply("ఆ")
    assert "could not be made out" not in model.requests[-1]["messages"][-1]["content"]


def test_silence_is_checked_twice_then_the_call_ends() -> None:
    model = FakeModel(message("opening"), message("అన్నా, ఉన్నారా?"), message("హలో అన్నా?"), message("తర్వాత కాల్ చేస్తా అన్నా."))
    convo, _ = conversation(model)
    convo.start()
    assert convo.on_silence() == "అన్నా, ఉన్నారా?"
    assert convo.on_silence() == "హలో అన్నా?"
    assert not convo.ended
    convo.on_silence()
    assert convo.ended and convo.state.end_reason == "the line went quiet"


def test_silence_after_a_settled_call_just_ends_it() -> None:
    model = FakeModel(message("opening"), message("సరే అండి, ధన్యవాదాలు.", ("set_outcome", {"outcome": "not_available"})))
    convo, _ = conversation(model)
    convo.start()
    convo.reply("busy అండి")
    assert convo.on_silence() is None  # no "are you there?" after a goodbye
    assert convo.ended and convo.state.end_reason == "the conversation was finished"


def test_speaking_resets_the_silence_count() -> None:
    model = FakeModel(message("opening"), message("ఉన్నారా?"), message("సరే"), message("ఉన్నారా?"), message("హలో?"))
    convo, _ = conversation(model)
    convo.start()
    convo.on_silence()
    convo.reply("ఆ ఉన్నా")
    convo.on_silence()
    convo.on_silence()
    assert not convo.ended  # the count restarted when they spoke


def test_wrap_up_tells_the_agent_to_close() -> None:
    model = FakeModel(message("opening"), message("థ్యాంక్స్ అన్నా, బై."))
    convo, _ = conversation(model)
    convo.start()
    convo.wrap_up()
    sent = model.requests[-1]["messages"]
    assert "Time is nearly up" in sent[-2]["content"] and sent[-1]["content"].startswith("Status for you only")


def test_time_up_says_goodbye_and_ends() -> None:
    # The first live screening call was cut mid-question at the cap; now a goodbye is said.
    model = FakeModel(message("opening"), message("థ్యాంక్స్ అన్నా, బై."))
    convo, _ = conversation(model)
    convo.start()
    assert convo.time_up() == "థ్యాంక్స్ అన్నా, బై."
    assert "Time is up. Ask nothing more" in model.requests[-1]["messages"][-2]["content"]
    assert convo.ended and convo.state.end_reason == "time cap reached"
    assert convo.time_up() is None


def test_an_endless_goodbye_is_cut_short() -> None:
    # The pattern from an eval run: outcome known at once, then goodbye after goodbye.
    model = FakeModel(message("opening"),
                      message("సరే అండి, అర్థమైంది.", ("set_outcome", {"outcome": "not_available"})),
                      message("సరే అండి, థ్యాంక్స్."), message("never reached"))
    convo, _ = conversation(model)
    convo.start()
    convo.reply("సారీ అండి, పది రోజులు fully booked.")
    assert not convo.ended  # one turn to say goodbye
    convo.reply("పర్లేదు అండి, జాగ్రత్త.")
    assert convo.ended and convo.state.end_reason == "the conversation was finished"


def test_an_early_call_customer_outcome_does_not_end_the_call() -> None:
    model = FakeModel(message("opening"),
                      message("fan తిరగట్లేదు అన్నా.", ("set_outcome", {"outcome": "call_customer"})),
                      message("sparks వస్తున్నాయి అన్నా."), message("ఎప్పుడు రావచ్చు?"))
    convo, _ = conversation(model)
    convo.start()
    for line in ("fan కి ఏమైంది?", "switchboard లో ఏమైంది?", "సరే, వస్తాను"):
        convo.reply(line)
    assert not convo.ended


def test_a_call_still_collecting_facts_is_not_cut_short() -> None:
    model = FakeModel(message("opening"),
                      message("సరే, ఎప్పుడు రావచ్చు?", ("set_outcome", {"outcome": "available"})),
                      message("charge ఎంత?"), message("సరే"))
    convo, _ = conversation(model)
    convo.start()
    for line in ("వస్తాను", "రేపు 10కి", "చెప్పండి"):
        convo.reply(line)
    assert not convo.ended  # available, but the time and charge are still missing


def test_a_looping_model_is_cut_off() -> None:
    loop = message(None, ("set_outcome", {"outcome": "maybe"}))  # refused every time
    model = FakeModel(message("opening"), *[loop] * 10)
    convo, _ = conversation(model)
    convo.start()
    convo.reply("hello")
    assert len(model.requests) == 1 + 5  # opening plus the per-turn limit


def test_the_first_reply_streams_to_the_runner_as_it_is_written() -> None:
    model = FakeModel(message("opening"), message("సరే అన్నా, రేపు 11కి."))
    convo, _ = conversation(model)
    convo.start()
    heard: list[str] = []
    convo.on_text = heard.append
    assert convo.reply("రేపు 11కి వస్తా") == "సరే అన్నా, రేపు 11కి."
    assert heard == ["సరే అన్నా, రేపు 11కి."]


def test_only_the_first_message_of_a_reply_is_spoken() -> None:
    # The larger model sent the same greeting twice, as two messages in one reply.
    model = FakeModel()
    convo, _ = conversation(model)
    model.responses = SimpleNamespace(create=lambda **kw: iter([
        SimpleNamespace(type="response.output_text.delta", item_id="msg_1", delta="నమస్తే అండి."),
        SimpleNamespace(type="response.output_text.delta", item_id="msg_2", delta="నమస్తే అండి."),
        SimpleNamespace(type="response.completed", response=SimpleNamespace(output=[]))]))
    assert convo.start() == "నమస్తే అండి."


def test_the_runner_does_not_need_livekit() -> None:
    assert not any(name.startswith("livekit") for name in sys.modules if "text_mode" in name)
    import voice.text_mode as module
    source = open(module.__file__, encoding="utf-8").read()
    assert "livekit" not in source.lower()


def test_a_mumble_after_the_goodbye_ends_the_call() -> None:
    # From a real call: after the goodbye, a "haa" came back in Gujarati script and the
    # agent asked them to repeat it.
    model = FakeModel(message("opening"), message("సరే, థ్యాంక్స్.", ("set_outcome", {"outcome": "not_available"})))
    convo, _ = conversation(model)
    convo.start()
    convo.reply("busy అండి")
    assert convo.reply(chr(0x0AB9) + chr(0x0ABE) + ".") is None
    assert convo.ended and convo.state.end_reason == "the conversation was finished"
