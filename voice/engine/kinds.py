"""Conversation kinds, loaded from voice/kinds.yaml, and the records built from them.

A kind says what sort of conversation this is. A conversation record is one
kind filled in for one job: the language, what may be shared, any extra
questions from the brief, and what memory already knows.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from backend.models import ConversationRecord, FactSpec, Language

KINDS_PATH = Path(__file__).resolve().parent.parent / "kinds.yaml"

# The tools the conversation engine provides (docs/LLD.md, section 9).
TOOL_NAMES = frozenset({"record_fact", "set_outcome", "mark_do_not_call", "end_conversation"})


class Kind(BaseModel):
    name: str
    channel: Literal["phone", "browser"]
    acting_for: str
    counterpart: str
    goal: str
    facts: list[FactSpec]
    opening_requirements: list[str] = Field(min_length=1)
    opening_must_not: list[str] = Field(default_factory=list)
    second_turn_requirements: list[str] = Field(default_factory=list)
    # Follow the language the person speaks, even from English (builder's requirement,
    # Sat 21 Nov). A kind held in one language on purpose sets this to false.
    follow_language: bool = True
    withheld: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    end_when: str
    tools: list[str] = Field(min_length=1)

    @field_validator("tools")
    @classmethod
    def _known_tools(cls, tools: list[str]) -> list[str]:
        unknown = set(tools) - TOOL_NAMES
        if unknown:
            raise ValueError(f"unknown tools: {sorted(unknown)}")
        if "end_conversation" not in tools:
            raise ValueError("every kind needs end_conversation, or a conversation could never end")
        return tools

    @field_validator("facts")
    @classmethod
    def _unique_fact_names(cls, facts: list[FactSpec]) -> list[FactSpec]:
        names = [f.name for f in facts]
        if len(names) != len(set(names)):
            raise ValueError("fact names must be unique within a kind")
        return facts


def load_kinds(path: Path = KINDS_PATH) -> dict[str, Kind]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {name: Kind(name=name, **body) for name, body in raw.items()}


@lru_cache
def _default_kinds() -> dict[str, Kind]:
    return load_kinds()


def get_kind(name: str, kinds: dict[str, Kind] | None = None) -> Kind:
    kinds = kinds if kinds is not None else _default_kinds()
    if name not in kinds:
        raise KeyError(f"no conversation kind named {name!r}")
    return kinds[name]


def build_record(kind_name: str, language: Language, *, time_cap_seconds: int,
                 wrap_up_at_seconds: int | None = None, shareable: dict[str, str] | None = None,
                 extra_facts: list[FactSpec] | None = None, known: list[str] | None = None,
                 kinds: dict[str, Kind] | None = None) -> ConversationRecord:
    """Fill in a kind for one conversation.

    `shareable` holds only what the agent may say out loud. Anything it must
    not reveal is left out entirely: the kind's `withheld` list tells the agent
    how to answer if asked, but the values never reach it.
    """
    kind = get_kind(kind_name, kinds)
    facts = list(kind.facts)
    taken = {f.name for f in facts}
    for fact in extra_facts or []:
        if fact.name not in taken:
            facts.append(fact)
            taken.add(fact.name)
    return ConversationRecord(
        kind=kind.name,
        language=language,
        goal=kind.goal,
        facts_to_collect=facts,
        shareable=dict(shareable or {}),
        withheld=list(kind.withheld),
        known=list(known or []),
        opening_requirements=list(kind.opening_requirements),
        second_turn_requirements=list(kind.second_turn_requirements),
        time_cap_seconds=time_cap_seconds,
        wrap_up_at_seconds=wrap_up_at_seconds,
    )
