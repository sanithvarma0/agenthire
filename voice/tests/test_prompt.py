"""Tests for the conversation kinds, the record builder and the prompt builder."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.models import FactSpec, Language
from voice.engine.kinds import KINDS_PATH, build_record, get_kind, load_kinds
from voice.engine.prompt import build_instructions, status_note

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"


def instructions(record, speaker_gender: str = "male") -> str:
    return build_instructions(record, speaker_gender)


def home_record(**overrides):
    values = dict(
        time_cap_seconds=180, wrap_up_at_seconds=150,
        shareable={"work": "a ceiling fan is not working", "area": "Gachibowli, Hyderabad",
                   "wanted": "tomorrow morning"},
    )
    values.update(overrides)
    return build_record("home_call", Language.TELUGU, **values)


# --- kinds ------------------------------------------------------------------

def test_both_kinds_load_and_are_valid() -> None:
    kinds = load_kinds()
    assert {"brief", "home_call"} <= set(kinds)
    assert kinds["home_call"].channel == "phone"
    assert kinds["brief"].channel == "browser"


def test_home_call_opens_like_a_local_householder() -> None:
    kind = get_kind("home_call")
    requirements = " ".join(kind.opening_requirements).lower()
    # First turn: greet and check who answered, nothing more.
    for expected in ("greet", "respectful", "calling"):
        assert expected in requirements, expected
    for word in ("customer", "recorded", "ai"):
        assert word not in requirements.split(), word
    assert any("describe the problem" in item for item in kind.opening_must_not)
    # Second turn: colony and locality, the problem, and the ask.
    second = " ".join(kind.second_turn_requirements).lower()
    for expected in ("colony and the locality", "problem at home", "come and take a look"):
        assert expected in second, expected
    assert "wrong_number" in " ".join(kind.rules)


def test_the_second_turn_is_in_the_prompt_and_reminded_once() -> None:
    record = home_record()
    assert "# Your second turn" in instructions(record)
    reminder = "This is your second turn"
    assert reminder in status_note(record, collected=[], seconds_elapsed=5, replies_so_far=0)
    assert reminder not in status_note(record, collected=[], seconds_elapsed=20, replies_so_far=1)
    assert reminder not in status_note(record, collected=[], seconds_elapsed=20)


def test_home_call_never_denies_being_an_ai_or_invents_an_identity() -> None:
    text = instructions(home_record())
    assert "answer honestly that you are an AI" in text
    assert "Never deny being an AI" in text
    assert "never claim to be a human" in text
    assert "Never invent a name" in text


def test_a_kind_with_an_unknown_tool_is_refused(tmp_path) -> None:
    path = tmp_path / "kinds.yaml"
    path.write_text(
        KINDS_PATH.read_text(encoding="utf-8").replace("tools: [record_fact, end_conversation]",
                                                       "tools: [record_fact, end_conversation, send_money]"),
        encoding="utf-8")
    with pytest.raises(ValueError, match="unknown tools"):
        load_kinds(path)


def test_unknown_kind_is_an_error() -> None:
    with pytest.raises(KeyError):
        get_kind("no_such_kind")


# --- records ----------------------------------------------------------------

def test_record_adds_extra_questions_after_the_base_facts() -> None:
    record = home_record(extra_facts=[
        FactSpec(name="brings_parts", description="Whether they bring spare parts", required=False),
        FactSpec(name="visiting_charge", description="duplicate of a base fact"),
    ])
    names = [f.name for f in record.facts_to_collect]
    assert names == ["available", "earliest_time", "visiting_charge", "brings_parts"]
    assert record.time_cap_seconds == 180


# --- instructions -----------------------------------------------------------

def test_instructions_carry_the_record() -> None:
    text = instructions(home_record(known=["Spoke Telugu on the last call"]))
    assert "Speak Telugu, in the relaxed" in text
    assert "never formal, written or textbook Telugu" in text
    assert "switch to the language they are speaking and stay in it" in text
    assert "Write Telugu words in Telugu's own script" in text
    for expected in ("a ceiling fan is not working", "Gachibowli, Hyderabad", "available", "earliest_time",
                     "visiting_charge", "come and take a look", "Spoke Telugu on the last call"):
        assert expected in text


def test_style_guidance_comes_from_the_style_files() -> None:
    from voice.engine.prompt import load_style
    text = instructions(home_record())
    telugu, hindi = load_style(Language.TELUGU), load_style(Language.HINDI)
    # Telugu (the starting language) first, then Hindi in case the call switches.
    assert text.index("# How to talk in Telugu") < text.index("# How to talk in Hindi")
    for style in (telugu, hindi):
        assert style["rules"][0] in text
        assert style["examples"][0]["natural"] in text
    assert "do not copy them word for word" in text


def test_an_english_conversation_that_follows_the_person_gets_indian_style_guidance() -> None:
    # It may switch to Telugu or Hindi, so it needs to know how to speak them.
    text = instructions(build_record("brief", Language.ENGLISH, time_cap_seconds=300))
    assert "# How to talk in Telugu" in text and "# How to talk in Hindi" in text


def test_an_english_conversation_held_in_english_gets_none(monkeypatch) -> None:
    from voice.engine.kinds import get_kind
    kind = get_kind("brief").model_copy(update={"follow_language": False})
    text = build_instructions(build_record("brief", Language.ENGLISH, time_cap_seconds=300), "male", kind)
    assert "# How to talk in" not in text and "reply in English" in text


def test_a_language_without_a_style_file_is_fine(tmp_path) -> None:
    from voice.engine.prompt import style_section
    assert style_section(Language.TELUGU, style_dir=tmp_path) == ""


def test_instructions_follow_the_brief_not_a_built_in_trade() -> None:
    text = instructions(home_record(shareable={"work": "the kitchen tap is leaking", "area": "Kondapur"}))
    assert "kitchen tap" in text
    assert "ceiling fan" not in text


def test_withheld_items_are_described_but_have_no_values() -> None:
    record = home_record()
    text = instructions(record)
    assert "the phone number of the person who needs the work" in text
    # The full address may be given, but only if asked (builder's decision, 21 Nov).
    assert "full address" in text and "only if they ask" in text
    # The record has nowhere to hold the user's number, so it cannot leak.
    assert not any(re.search(r"\+?\d{10,}", value) for value in record.shareable.values())


def test_english_conversations_follow_a_person_who_speaks_another_language() -> None:
    record = build_record("brief", Language.ENGLISH, time_cap_seconds=300)
    text = instructions(record)
    assert "Speak English" in text and "switch to the language they are speaking" in text


def test_an_english_brief_switches_when_the_user_speaks_telugu() -> None:
    from voice.engine.state import ConversationState
    state = ConversationState(build_record("brief", Language.ENGLISH, time_cap_seconds=300))
    state.person_said("మా ఇంట్లో fan పని చేయట్లేదు అండి")
    assert state.reply_language is Language.TELUGU


def test_voice_gender_comes_from_settings_not_code() -> None:
    from backend.settings import load_settings
    voice = load_settings().voice
    assert voice.voice_for("te")[0] == "kavitha_te_conversation" and voice.gender_for("te") == "female"
    assert voice.voice_for("hi")[0] == "shubh" and voice.gender_for("hi") == "male"
    assert "spoken in a female voice" in instructions(home_record(), speaker_gender=voice.gender_for("te"))


def test_every_language_must_use_a_listed_voice() -> None:
    import pytest
    from backend.settings import VoiceSettings
    with pytest.raises(ValueError, match="not in voice.voices"):
        VoiceSettings(agent_name="a", stt_model="m", stt_mode="codemix", stt_language="unknown",
                      voices={"shubh": {"model": "bulbul:v3", "gender": "male"}},
                      language_voice={"te": "someone_else"})


def test_a_language_switch_also_switches_the_voice_gender() -> None:
    from backend.models import Language
    from voice.engine.state import ConversationState
    genders = {Language.TELUGU: "female", Language.HINDI: "male"}
    state = ConversationState(home_record(), gender_for=genders.get)
    assert "voice" not in state.status()  # no switch yet
    state.person_said("हाँ भाई, कल आ जाऊँगा")
    assert "now spoken in a male voice" in state.status()


def test_the_agent_is_told_not_to_repeat_its_question() -> None:
    assert "Never end two turns in a row with the same question" in instructions(home_record())


def test_replies_are_told_to_be_speakable() -> None:
    assert "no slashes" in instructions(home_record())


def test_optional_facts_are_marked() -> None:
    text = instructions(home_record())
    assert "available: Whether they can take this job" in text and "(if it comes up naturally)" in text


def test_the_brief_asks_only_about_the_problem() -> None:
    text = instructions(build_record("brief", Language.TELUGU, time_cap_seconds=300))
    assert "service:" in text and "work:" in text
    assert "budget:" not in text and "time_window:" not in text


# --- status note ------------------------------------------------------------

def test_status_lists_what_is_missing() -> None:
    note = status_note(home_record(), collected=["available"], seconds_elapsed=40)
    assert "Already found out: available." in note
    assert "Still to find out: earliest_time, visiting_charge." in note
    assert "about 140 seconds" in note
    assert "Wrap up now" not in note


def test_status_says_to_wrap_up_near_the_cap() -> None:
    note = status_note(home_record(), collected=[], seconds_elapsed=155)
    assert "Wrap up now" in note


def test_status_says_to_close_when_everything_is_found() -> None:
    note = status_note(home_record(), collected=["available", "earliest_time", "visiting_charge"],
                       seconds_elapsed=60)
    assert "Everything is found" in note


# --- no hardcoding ----------------------------------------------------------

def test_engine_and_kinds_contain_no_trades_places_or_scripted_indian_text() -> None:
    """docs/LLD.md, section 1: no fixed sentences, word lists or built-in categories."""
    files = [KINDS_PATH, *ENGINE_DIR.glob("*.py")]
    banned = re.compile(r"electrician|plumber|carpenter|\bAC repair\b|Hyderabad|Gachibowli|Kondapur|Raidurg",
                        re.IGNORECASE)
    indian_script = re.compile(r"[ऀ-ॿఀ-౿]")  # Devanagari and Telugu
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not banned.search(text), f"{path.name} names a trade or place"
        assert not indian_script.search(text), f"{path.name} contains scripted Hindi or Telugu text"
