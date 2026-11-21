"""Tests for the eval checks themselves, with made-up results and transcripts."""

from __future__ import annotations

from datetime import datetime

from backend.models import CallResult, CollectedFact, Language, Outcome, TranscriptLine
from evals.run import check_conduct, check_language, check_result, load_scenarios

TODAY = datetime(2026, 11, 21, 19, 0)


def fact(name: str, value: str, verified: bool = True) -> CollectedFact:
    return CollectedFact(name=name, value=value, said_as="x", evidence_seq=1, verified=verified)


EXPECT = {
    "outcome": "available",
    "facts": {"available": {"equals": "yes"}, "earliest_time": {"date_offset": 1, "contains": "11:00"},
              "visiting_charge": {"equals": "200"}},
    "language_spoken": "te",
}


def good_result(**overrides) -> CallResult:
    values = dict(outcome=Outcome.AVAILABLE, language_spoken=Language.TELUGU, facts=[
        fact("available", "yes"), fact("earliest_time", "2026-11-22 11:00"), fact("visiting_charge", "200")])
    values.update(overrides)
    return CallResult(**values)


def test_the_scenarios_file_is_valid() -> None:
    scenarios = load_scenarios()
    assert [s["id"] for s in scenarios] == ["available_te", "asks_first_te", "busy_te", "voicemail", "hindi_reply",
                                               "wrong_number", "confirm_te", "confirm_moved_te",
                                               "brief_te", "brief_mixed_en", "screening_interested",
                                               "screening_not_interested"]
    for s in scenarios:
        assert {"kind", "language", "job", "persona", "persona_language", "expect"} <= set(s)


def test_a_matching_result_passes() -> None:
    assert check_result(EXPECT, good_result(), TODAY) == []


def test_wrong_outcome_value_and_date_are_reported() -> None:
    result = good_result(outcome=Outcome.NOT_AVAILABLE, facts=[
        fact("available", "yes"), fact("earliest_time", "2026-11-23 11:00"), fact("visiting_charge", "250")])
    failures = check_result(EXPECT, result, TODAY)
    assert "outcome is not_available, expected available" in failures
    assert "visiting_charge is '250', expected '200'" in failures
    assert "earliest_time is '2026-11-23 11:00', expected the date 2026-11-22" in failures


def test_missing_and_unconfirmed_facts_are_reported() -> None:
    result = good_result(facts=[fact("available", "yes", verified=False), fact("earliest_time", "2026-11-22 11:00")])
    failures = check_result(EXPECT, result, TODAY)
    assert "available is not confirmed by the transcript" in failures
    assert "visiting_charge is missing" in failures


def test_a_fact_that_should_be_absent_is_reported() -> None:
    failures = check_result({"outcome": "not_available", "absent": ["visiting_charge"]},
                            CallResult(outcome=Outcome.NOT_AVAILABLE, facts=[fact("visiting_charge", "300")]), TODAY)
    assert failures == ["visiting_charge should not be in the result, but is '300'"]


def lines(*spoken: tuple[str, str]) -> list[TranscriptLine]:
    return [TranscriptLine(seq=i + 1, speaker=who, text=text) for i, (who, text) in enumerate(spoken)]


def test_good_conduct_passes() -> None:
    transcript = lines(("agent", "అన్నా నమస్తే, మా ఇంట్లో fan పని చేయట్లేదు."), ("person", "సరే"))
    assert check_conduct(transcript, Language.TELUGU, "done") == []


def test_unprompted_ai_mention_slashes_and_english_letters_are_reported() -> None:
    transcript = lines(("agent", "నేను AI assistant ని"), ("agent", "బోల్ రహా/రహీ"), ("agent", "Namaste anna"))
    failures = check_conduct(transcript, Language.TELUGU, "done")
    assert "line 1: mentions being an AI without being asked" in failures
    assert "line 2: contains characters a voice cannot speak" in failures
    assert "lines [3]: written only in English letters" in failures


def test_a_doubled_question_and_a_stray_script_are_reported() -> None:
    doubled = ("రేపు 11 గంటలే కదా, సరే. visiting charge ఎంత తీసుకుంటారు అన్నా? "
               "రేపు 11 గంటలకు వస్తా అన్నట్టు తీసుకున్నాను. వచ్చి చూసే charge ఎంత తీసుకుంటారు అన్నా?")
    stray = chr(0x660E) + "ుదు, tomorrow 11 అంటే?"
    transcript = lines(("agent", "అన్నా నమస్తే"), ("agent", doubled), ("agent", stray))
    failures = check_conduct(transcript, Language.TELUGU, "done")
    assert "line 2: says the same thing twice" in failures
    assert "line 3: contains characters a voice cannot speak" in failures


def test_the_same_question_two_turns_in_a_row_is_reported() -> None:
    # The pattern from the first real call (lines 4 and 6 there).
    transcript = lines(
        ("agent", "అంటే అన్నా, ఒక switchboard దగ్గర నుంచి చిన్న చిన్న sparks వస్తున్నాయి. మీరు వచ్చి చూసి చెయ్యగలరా?"),
        ("person", "ఇంకా fans కి ఏమైంది?"),
        ("agent", "ఒక room లో fan ఆడట్లేదు అన్నా. మీరు ఇది చూసి చెయ్యగలరా?"),
    )
    assert check_conduct(transcript, Language.TELUGU, "done") == ["line 3: ends with the same question as line 1"]


def test_answering_without_re_asking_passes() -> None:
    transcript = lines(
        ("agent", "అన్నా నమస్తే, మా ఇంట్లో fan పని చేయట్లేదు. మీరు వచ్చి చూసి చెయ్యగలరా?"),
        ("person", "ఇంకా fans కి ఏమైంది?"),
        ("agent", "ఒక room లో fan ఆడట్లేదు అన్నా, కొన్ని switches కూడా పని చేయట్లేదు."),
    )
    assert check_conduct(transcript, Language.TELUGU, "done") == []


def test_a_spoken_tool_call_is_reported() -> None:
    transcript = lines(("agent", '"name":"available","value":"yes" సరే అన్నా'))
    assert "line 1: speaks a tool call out loud" in check_conduct(transcript, Language.TELUGU, "done")


def test_saying_ai_after_being_asked_is_fine() -> None:
    transcript = lines(("person", "నువ్వు robot ఆ?"), ("agent", "అవును అన్నా, నేను AI ని"))
    assert check_conduct(transcript, Language.TELUGU, "done") == []


def test_switching_to_hindi_on_a_telugu_call_is_allowed() -> None:
    transcript = lines(("agent", "ठीक है भाई, कल आ जाओ"))
    assert check_conduct(transcript, Language.TELUGU, "done") == []


def test_the_agent_must_switch_after_the_person_answers_in_hindi() -> None:
    switched = lines(("agent", "అన్నా నమస్తే, వచ్చి చూస్తారా?"), ("person", "हाँ भाई, आता हूँ"),
                     ("agent", "ठीक है भाई, कितना लगेगा?"))
    stayed = lines(("agent", "అన్నా నమస్తే, వచ్చి చూస్తారా?"), ("person", "हाँ भाई, आता हूँ"),
                   ("agent", "సరే అన్నా, charge ఎంత?"))
    assert check_language(switched, Language.TELUGU, Language.HINDI) == []
    assert check_language(stayed, Language.TELUGU, Language.HINDI) == ["lines [3]: not in Hindi after the person spoke it"]


def test_without_a_switch_the_agent_must_stay_in_the_calls_language() -> None:
    drifted = lines(("agent", "అన్నా నమస్తే"), ("person", "చెప్పండి, ok"), ("agent", "ठीक है भाई"))
    assert check_language(drifted, Language.TELUGU, None) == ["lines [3]: not in Telugu"]


def test_a_conversation_that_never_ended_is_reported() -> None:
    transcript = lines(("agent", "అన్నా నమస్తే"))
    assert check_conduct(transcript, Language.TELUGU, "turn limit reached") == [
        "the conversation did not end properly (turn limit reached)"]
