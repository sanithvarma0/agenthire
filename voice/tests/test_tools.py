"""Tests for the conversation state and the four tools."""

from __future__ import annotations

from backend.models import EventType, Language, Outcome
from voice.engine.kinds import build_record
from voice.engine.state import ConversationState
from voice.engine.tools import call_tool, tool_specs


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_state(kind: str = "home_call", clock: FakeClock | None = None) -> tuple[ConversationState, list]:
    events: list[tuple[EventType, dict]] = []
    record = build_record(kind, Language.TELUGU, time_cap_seconds=180, wrap_up_at_seconds=150,
                          shareable={"work": "a fan is not working", "area": "Madhapur"})
    state = ConversationState(record, emit=lambda type_, payload: events.append((type_, payload)),
                              clock=clock or FakeClock())
    return state, events


def types(events: list) -> list[EventType]:
    return [type_ for type_, _ in events]


# --- schemas ----------------------------------------------------------------

def test_specs_offer_only_the_kinds_tools() -> None:
    home, _ = make_state("home_call")
    brief, _ = make_state("brief")
    assert [s["function"]["name"] for s in tool_specs(home)] == [
        "record_fact", "set_outcome", "mark_do_not_call", "end_conversation"]
    assert [s["function"]["name"] for s in tool_specs(brief)] == ["record_fact", "end_conversation"]


def test_fact_names_are_limited_to_the_record() -> None:
    state, _ = make_state()
    record_fact = next(s for s in tool_specs(state) if s["function"]["name"] == "record_fact")
    assert record_fact["function"]["parameters"]["properties"]["name"]["enum"] == [
        "available", "earliest_time", "visiting_charge"]


def test_the_agent_can_report_voicemail_as_no_answer() -> None:
    state, _ = make_state()
    set_outcome = next(s for s in tool_specs(state) if s["function"]["name"] == "set_outcome")
    assert "no_answer" in set_outcome["function"]["parameters"]["properties"]["outcome"]["enum"]
    assert "voicemail" in set_outcome["function"]["description"]
    assert call_tool(state, "set_outcome", {"outcome": "no_answer"}) == "Outcome set to no_answer."
    assert call_tool(state, "end_conversation", {"reason": "voicemail"}) == "Ending the conversation."


# --- record_fact ------------------------------------------------------------

def test_recording_a_fact_updates_state_status_and_events() -> None:
    state, events = make_state()
    state.person_said("విజిట్ చార్జ్ మూడు వందలు అన్నా, పని చూసాక మిగతాది చెప్తా.")
    reply = call_tool(state, "record_fact", {"name": "visiting_charge", "value": "300",
                                             "said_as": "మూడు వందలు అన్నా"})
    assert reply == "Recorded visiting_charge. Still to find out: earliest_time."  # availability is optional
    assert state.facts["visiting_charge"].value == "300"
    assert "Still to find out: earliest_time." in state.status()
    assert types(events) == [EventType.FACT_RECORDED, EventType.TOOL_CALLED]
    assert events[0][1] == {"name": "visiting_charge", "value": "300", "said_as": "మూడు వందలు అన్నా"}


def test_a_correction_replaces_the_earlier_value() -> None:
    state, _ = make_state()
    state.person_said("300")
    state.person_said("sorry, 250")
    call_tool(state, "record_fact", {"name": "visiting_charge", "value": "300", "said_as": "300"})
    call_tool(state, "record_fact", {"name": "visiting_charge", "value": "250", "said_as": "sorry, 250"})
    assert state.facts["visiting_charge"].value == "250"


def test_unknown_or_empty_facts_are_refused() -> None:
    state, events = make_state()
    assert call_tool(state, "record_fact", {"name": "favourite_colour", "value": "blue",
                                            "said_as": "blue"}).startswith("Refused: unknown fact")
    assert call_tool(state, "record_fact", {"name": "available", "value": " ",
                                            "said_as": "yes"}).startswith("Refused")
    assert state.facts == {}
    assert types(events) == [EventType.TOOL_CALLED, EventType.TOOL_CALLED]  # refusals are still logged


def test_a_fact_nobody_said_is_refused() -> None:
    state, events = make_state()
    state.person_said("कौन बोल रहा है?")
    state.person_said("मुझे ये सब नहीं चाहिए, दोबारा call मत करना।")
    reply = call_tool(state, "record_fact", {"name": "visiting_charge", "value": "300",
                                             "said_as": "तीन सौ रुपये लगेंगे"})
    assert reply.startswith("Refused: the other person has not said that")
    assert state.facts == {}
    assert EventType.FACT_RECORDED not in types(events)
    assert types(events)[-1] == EventType.TOOL_CALLED


def test_nothing_can_be_recorded_before_the_person_speaks() -> None:
    state, _ = make_state()
    assert call_tool(state, "record_fact", {"name": "available", "value": "yes",
                                            "said_as": "yes"}).startswith("Refused")


def test_a_quote_may_be_trimmed_or_lose_punctuation() -> None:
    state, _ = make_state()
    state.person_said("సరే, రేపు ఉదయం పది గంటలకు రాగలను.")
    assert state.was_said("రేపు ఉదయం పది గంటలకు రాగలను")
    assert state.was_said("సరే రేపు ఉదయం పది గంటలకు")
    assert not state.was_said("ఎల్లుండి సాయంత్రం వస్తాను")


def test_arguments_may_arrive_as_json_text() -> None:
    state, _ = make_state()
    state.person_said("సరే వస్తాను")
    call_tool(state, "record_fact", '{"name": "available", "value": "yes", "said_as": "వస్తాను"}')
    assert state.facts["available"].value == "yes"


def test_all_facts_found() -> None:
    state, _ = make_state()
    state.person_said("x")
    state.person_said("300")
    for name in ("available", "earliest_time"):
        call_tool(state, "record_fact", {"name": name, "value": "x", "said_as": "x"})
    reply = call_tool(state, "record_fact", {"name": "visiting_charge", "value": "300", "said_as": "300"})
    assert reply.endswith("All required facts are found.")
    assert "Everything is found" in state.status()


# --- outcome, do-not-call, ending -------------------------------------------

def test_set_outcome_rejects_made_up_values() -> None:
    state, _ = make_state()
    assert call_tool(state, "set_outcome", {"outcome": "maybe"}).startswith("Refused")
    assert call_tool(state, "set_outcome", {"outcome": "available"}) == "Outcome set to available."
    assert state.outcome is Outcome.AVAILABLE


def test_a_home_call_cannot_end_without_an_outcome() -> None:
    state, _ = make_state()
    assert call_tool(state, "end_conversation", {"reason": "done"}).startswith("Refused: call set_outcome")
    assert not state.ended
    call_tool(state, "set_outcome", {"outcome": "not_available"})
    assert call_tool(state, "end_conversation", {"reason": "busy all week"}) == "Ending the conversation."
    assert state.ended and state.end_reason == "busy all week"


def test_an_available_provider_cannot_be_hung_up_on_before_the_charge_is_asked() -> None:
    clock = FakeClock()
    state, _ = make_state(clock=clock)
    state.person_said("అవును అన్నా, రేపు 11 గంటలకు రావచ్చు.")
    call_tool(state, "record_fact", {"name": "available", "value": "yes", "said_as": "అవును అన్నా"})
    call_tool(state, "record_fact", {"name": "earliest_time", "value": "2026-11-22 11:00",
                                     "said_as": "రేపు 11 గంటలకు రావచ్చు"})
    call_tool(state, "set_outcome", {"outcome": "available"})
    reply = call_tool(state, "end_conversation", {"reason": "Need visiting charge"})
    assert reply == ("Refused: they are taking part, but you still need: visiting_charge. "
                     "Ask about it now, then end.")
    assert not state.ended
    clock.now += 150  # at wrap-up time, ending with what was found is allowed
    assert call_tool(state, "end_conversation", {"reason": "time"}) == "Ending the conversation."


def test_a_short_quote_must_be_said_word_for_word() -> None:
    # From a real call: a made-up three-word quote shared two words with a question.
    state, _ = make_state()
    state.person_said("ఆ issue ఏంది? మళ్ళీ చెప్పండి ఒకసారి.")
    reply = call_tool(state, "record_fact", {"name": "available", "value": "yes", "said_as": "ఆ issue చూస్తాం"})
    assert reply.startswith("Refused: the other person has not said that")
    assert call_tool(state, "record_fact", {"name": "available", "value": "yes",
                                            "said_as": "ఆ issue ఏంది"}).startswith("Recorded")


def test_a_provider_who_cannot_take_the_job_can_be_let_go_at_once() -> None:
    state, _ = make_state()
    call_tool(state, "set_outcome", {"outcome": "not_available"})
    assert call_tool(state, "end_conversation", {"reason": "busy"}) == "Ending the conversation."


def test_nothing_changes_after_the_end() -> None:
    state, _ = make_state()
    call_tool(state, "set_outcome", {"outcome": "available"})
    call_tool(state, "end_conversation", {"reason": "done"})
    assert call_tool(state, "record_fact", {"name": "available", "value": "yes",
                                            "said_as": "yes"}).startswith("Refused")


def test_a_brief_can_end_without_an_outcome() -> None:
    state, _ = make_state("brief")
    assert call_tool(state, "end_conversation", {"reason": "user confirmed"}) == "Ending the conversation."


def test_a_tool_outside_the_kind_is_refused() -> None:
    state, _ = make_state("brief")
    assert call_tool(state, "set_outcome", {"outcome": "available"}).startswith("Refused")
    assert call_tool(state, "send_money", {}).startswith("Refused")


def test_do_not_call_sets_declined_and_reaches_the_result() -> None:
    state, events = make_state()
    call_tool(state, "mark_do_not_call", {})
    assert state.outcome is Outcome.DECLINED
    result = state.live_result()
    assert result.do_not_call and result.outcome is Outcome.DECLINED
    assert EventType.OUTCOME_SET in types(events)


def test_do_not_call_ends_the_call_after_the_next_reply_even_if_the_model_forgets() -> None:
    state, _ = make_state()
    call_tool(state, "mark_do_not_call", {})
    assert not state.ended  # the apology still has to be spoken
    state.after_agent_reply()
    assert state.ended and state.end_reason == "asked not to be called again"


def test_an_ordinary_reply_does_not_end_the_call() -> None:
    state, _ = make_state()
    state.after_agent_reply()
    assert not state.ended


def test_recording_needs_a_clear_answer() -> None:
    from voice.engine.prompt import build_instructions
    text = build_instructions(state_record(), "male")
    assert "A greeting, an invitation to go on, or a question back to you is not an answer" in text


def state_record():
    state, _ = make_state()
    return state.record


def test_do_not_call_keeps_an_outcome_already_set() -> None:
    state, _ = make_state()
    call_tool(state, "set_outcome", {"outcome": "wrong_number"})
    call_tool(state, "mark_do_not_call", {})
    assert state.outcome is Outcome.WRONG_NUMBER and state.do_not_call


# --- time -------------------------------------------------------------------

def test_the_reply_language_follows_the_person() -> None:
    state, events = make_state()
    state.person_said("చెప్పండి అన్నా, ok")
    assert state.reply_language is Language.TELUGU and "Reply in" not in state.status()
    state.person_said("हाँ भाई, आज शाम आ सकता हूँ")
    assert state.reply_language is Language.HINDI
    assert "The other person is speaking Hindi. Reply in Hindi now" in state.status()
    assert (EventType.LANGUAGE_CHANGED, {"language": "hi"}) in events


def test_one_short_word_does_not_switch_the_language() -> None:
    # On a real call, line noise came back as a one-word Hindi "no".
    state, _ = make_state()
    state.person_said("नहीं।")
    assert state.reply_language is Language.TELUGU
    state.person_said("नहीं भाई")  # a second line in Hindi does switch
    assert state.reply_language is Language.HINDI


def test_a_short_misheard_line_does_not_switch_the_language() -> None:
    # On a real call, Telugu speech came back as three words, two of them in Hindi script.
    state, _ = make_state()
    state.person_said("धनी question होता.")
    assert state.reply_language is Language.TELUGU
    state.person_said("Address చెప్పండి ఒకసారి.")  # back in Telugu: no switch happened
    assert state.reply_language is Language.TELUGU


def test_a_short_real_reply_in_another_language_does_switch() -> None:
    # From an eval run: the provider's first reply was short but plainly Hindi.
    state, _ = make_state()
    state.person_said("हाँ जी, Al-Noor Electricals. बोलिए.")
    assert state.reply_language is Language.HINDI


def test_english_letters_do_not_change_the_language() -> None:
    state, _ = make_state()
    state.person_said("ok ok, tell me the address")
    assert state.reply_language is Language.TELUGU


def test_status_tracks_time_and_wrap_up() -> None:
    clock = FakeClock()
    state, _ = make_state(clock=clock)
    clock.now += 60
    assert "about 120 seconds" in state.status()
    clock.now += 95
    assert "Wrap up now" in state.status()


def test_live_result_is_empty_until_an_outcome() -> None:
    state, _ = make_state()
    assert state.live_result() is None
