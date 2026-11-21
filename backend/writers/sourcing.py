"""Finds public profiles that fit an approved posting (docs/LLD.md, section 17).

One Responses call with OpenAI's web search tool: the model searches public pages and
returns up to ten people, each with their profile link. No LinkedIn sign-in, no
scraping and no browser agent (builder's decision, Sun 22 Nov). No phone number or email is
taken, so nobody found here is ever contacted: a screening call for one of them rings the
builder's own number instead (the demo fallback, docs/LLD.md, section 17).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from backend.settings import Settings

MAX_PROFILES = 10

INSTRUCTIONS = f"""You are a sourcing researcher for a recruiter. Search the public web for real people who may fit the role below,
preferring public LinkedIn profile pages (linkedin.com/in/...) of people working in or near the role's location.
Return up to {MAX_PROFILES} different people. Report only what the pages you found actually show; never invent a person, a link,
an employer or years of experience. If you cannot find a field, leave it "".
For each person:
- name: as shown on the page.
- headline: their current title or headline, as shown.
- company: their current employer, as shown, or "".
- location: as shown, or "".
- experience: one short line on the experience that matches the role, from the page (for example years in the field or the
  relevant tools), or "".
- profile_url: the link to their public profile.
Never include personal contact details (phone numbers, email addresses) even if a page shows them."""

_PROFILE = {"type": "object", "additionalProperties": False,
            "required": ["name", "headline", "company", "location", "experience", "profile_url"],
            "properties": {k: {"type": "string"} for k in
                           ("name", "headline", "company", "location", "experience", "profile_url")}}

SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "required": ["people"],
                          "properties": {"people": {"type": "array", "items": _PROFILE}}}


class Profile(BaseModel):
    """A person found on a public page. Display only."""

    name: str
    headline: str = ""
    company: str = ""
    location: str = ""
    experience: str = ""
    profile_url: str


def describe_role(role: dict[str, Any], posting: dict[str, Any]) -> str:
    lines = [f"Role: {posting.get('title') or role.get('role', '')}"]
    if role.get("must_haves"):
        lines.append(f"Must have: {', '.join(role['must_haves'])}")
    for key, label in (("experience", "Experience"), ("location", "Location")):
        if role.get(key):
            lines.append(f"{label}: {role[key]}")
    return "\n".join(lines)


def _web_link(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def find_profiles(role: dict[str, Any], posting: dict[str, Any], *, client: Any, settings: Settings) -> list[Profile]:
    response = client.responses.create(
        model=settings.secrets.llm_model_smart,
        reasoning={"effort": "low"},
        tools=[{"type": "web_search"}],
        instructions=INSTRUCTIONS,
        input=describe_role(role, posting),
        text={"format": {"type": "json_schema", "name": "profiles", "strict": True, "schema": SCHEMA}},
    )
    data = json.loads(response.output_text)
    found: list[Profile] = []
    seen: set[str] = set()
    for raw in data["people"]:
        person = Profile(**{k: str(v).strip() for k, v in raw.items()})
        key = person.profile_url.rstrip("/").lower()
        # A person with no name or no real link cannot be checked by HR, so they are not shown.
        if not person.name or not _web_link(person.profile_url) or key in seen:
            continue
        seen.add(key)
        found.append(person)
    return found[:MAX_PROFILES]
