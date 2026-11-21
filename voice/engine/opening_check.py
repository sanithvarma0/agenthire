"""Checks the agent's opening before it is spoken (docs/LLD.md, section 9).

The opening is generated while the phone is ringing, so there is time to check
it once against the kind's requirements (what it must say) and its
`opening_must_not` list (what it must not say), and to regenerate it if needed.
A model judges meaning, because the opening is in Telugu or Hindi and the
requirements are in English; no word lists are involved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.models import ConversationRecord
from voice.engine.kinds import Kind

INSTRUCTIONS = """You check the first thing a caller said when a phone call was picked up.
You get the opening, what it was about, a list of things it MUST do and a list of things it MUST NOT do.
Judge the meaning, in whatever language the opening is in.
Return the number of every MUST item the opening does not do, and of every MUST NOT item it does.
Return empty lists when the opening is fine."""


@dataclass
class OpeningCheck:
    missing: list[str] = field(default_factory=list)  # requirements not met
    broken: list[str] = field(default_factory=list)   # must-not items that were done

    @property
    def ok(self) -> bool:
        return not self.missing and not self.broken

    def feedback(self) -> str:
        """A note for regenerating the opening."""
        parts = []
        if self.missing:
            parts.append("Your opening must also: " + "; ".join(self.missing) + ".")
        if self.broken:
            parts.append("Your opening must not: " + "; ".join(self.broken) + ".")
        return " ".join(parts)


def _schema(record: ConversationRecord, kind: Kind) -> dict[str, Any]:
    # Items are answered by number: structured outputs do not allow every character in
    # enum strings (double quotes, for one), and requirements are free text.
    def items(values: list[str]) -> dict[str, Any]:
        numbers = list(range(1, len(values) + 1))
        return {"type": "array", "items": {"type": "integer", "enum": numbers}} if values else \
            {"type": "array", "items": {"type": "integer"}, "maxItems": 0}

    return {
        "type": "object", "additionalProperties": False, "required": ["missing", "broken"],
        "properties": {"missing": items(record.opening_requirements), "broken": items(kind.opening_must_not)},
    }


def _numbered(values: list[str]) -> str:
    return "\n".join(f"{i}. {value}" for i, value in enumerate(values, start=1))


def _pick(values: list[str], numbers: list[int]) -> list[str]:
    # Keep only numbers that really are on the list, in case a model returns anything else.
    return [values[n - 1] for n in dict.fromkeys(numbers) if isinstance(n, int) and 1 <= n <= len(values)]


def check_opening(opening: str, record: ConversationRecord, kind: Kind, *, client: Any, model: str) -> OpeningCheck:
    context = "\n".join(f"- {label}: {value}" for label, value in record.shareable.items())
    request = (f"Opening:\n{opening}\n\nWhat the call is about:\n{context}\n\n"
               f"MUST:\n{_numbered(record.opening_requirements)}\n\n"
               f"MUST NOT:\n{_numbered(kind.opening_must_not)}")
    response = client.chat.completions.create(
        model=model, reasoning_effort="none",
        messages=[{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": request}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "opening_check", "strict": True, "schema": _schema(record, kind)}},
    )
    data = json.loads(response.choices[0].message.content)
    return OpeningCheck(missing=_pick(record.opening_requirements, data["missing"]),
                        broken=_pick(kind.opening_must_not, data["broken"]))
