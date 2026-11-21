"""Turns what the user asked for into a Brief (docs/LLD.md, section 13).

Until the voice brief exists (task 3.6) the input is the request typed on the
Start screen; afterwards it is the brief conversation's transcript. The model
names the kind of provider in a few words, which become the Places search, so no
trade is listed in code.
"""

from __future__ import annotations

import json
from typing import Any

from backend.models import Brief
from backend.settings import Settings

INSTRUCTIONS = """You read what someone needs done at their home, in any language or a mix of languages.
It may be a typed request, or a conversation between them (USER) and an assistant (AGENT); use what the user said,
including corrections, and the summary they confirmed.
Return:
- service: the kind of local provider who does this work, in two or three plain English words, as someone would type it into a map search (for example the trade's common name). Never the problem itself.
- work: what needs doing, in one or two short plain English sentences, keeping every detail the person gave and adding nothing.
- understood: false only if the text does not say what needs doing at all."""

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["service", "work", "understood"],
    "properties": {
        "service": {"type": "string"},
        "work": {"type": "string"},
        "understood": {"type": "boolean"},
    },
}


class BriefNotUnderstood(ValueError):
    """The request did not say what needs doing."""


def write_brief(text: str, *, client: Any, settings: Settings) -> Brief:
    response = client.chat.completions.create(
        model=settings.secrets.llm_model_smart, reasoning_effort="low",
        messages=[{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": text}],
        response_format={"type": "json_schema", "json_schema": {"name": "brief", "strict": True, "schema": SCHEMA}},
    )
    data = json.loads(response.choices[0].message.content)
    if not data["understood"] or not data["service"].strip() or not data["work"].strip():
        raise BriefNotUnderstood("the request does not say what needs doing")
    return Brief(service=data["service"].strip(), work=data["work"].strip())
