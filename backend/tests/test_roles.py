"""Tests for the company side's start, posting writer and posting approval (docs/LLD.md,
section 17). The model is faked, so nothing goes over the network."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.db import Database
from backend.main import create_app
from backend.settings import load_settings
from backend.tests.test_jobs import NoDialler

QUESTION = {"question": "Tell me about a service you built.", "strong": "Owned it end to end, with numbers.",
            "average": "Worked on parts of one.", "weak": "No example."}
POSTING = {"understood": True, "role": "Backend Engineer", "must_haves": ["Python", "APIs"], "experience": "3+ years",
           "location": "Hyderabad, hybrid", "summary": "Builds the APIs behind the product.",
           "title": "Backend Engineer (Python)", "job_description": "You will build and run the APIs behind our product.",
           "questions": [QUESTION] * 5}


def profile(name: str, url: str, **extra: str) -> dict:
    base = {"name": name, "headline": "Data Engineer", "company": "Some Co", "location": "Hyderabad",
            "experience": "4 years of pipelines", "profile_url": url}
    return {**base, **extra}


PROFILES = [profile("Asha Rao", "https://in.linkedin.com/in/asha-rao"),
            profile("Asha Rao again", "https://in.linkedin.com/in/asha-rao/"),  # the same link: dropped
            profile("No Link", ""),  # no link HR could check: dropped
            profile("", "https://in.linkedin.com/in/nameless"),  # no name: dropped
            profile("Ravi Kumar", "https://in.linkedin.com/in/ravi-k", company="")]


class FakeModel:
    """Answers the posting writer (chat) and the sourcing search (responses) with fixed
    answers, and keeps what it was asked."""

    def __init__(self, answer: dict | None = None, profiles: list[dict] | None = None, search_fails: bool = False):
        self.answer = answer or POSTING
        self.profiles = PROFILES if profiles is None else profiles
        self.search_fails = search_fails
        self.asked: list[str] = []
        self.searched: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.responses = SimpleNamespace(create=self._search)

    def _create(self, **kwargs):
        self.asked.append(kwargs["messages"][-1]["content"])
        message = SimpleNamespace(content=json.dumps(self.answer), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def _search(self, **kwargs):
        self.searched.append(kwargs)
        if self.search_fails:
            raise TimeoutError("search timed out")
        return SimpleNamespace(output_text=json.dumps({"people": self.profiles}))


def client(model: FakeModel | None = None) -> TestClient:
    app = create_app(settings=load_settings(), database=Database(":memory:"), dialler=NoDialler())
    app.state.openai = model or FakeModel()
    return TestClient(app)


def edit(job: dict) -> dict:
    p = job["posting"]
    return {"title": p["title"], "job_description": p["job_description"], "questions": p["questions"]}


def test_a_typed_role_becomes_a_posting_to_approve() -> None:
    model = FakeModel()
    c = client(model)
    job_id = c.post("/roles", json={"company": "Acme Labs", "request": "Backend engineer, Python, 3 years"}).json()["id"]
    job = c.get(f"/jobs/{job_id}").json()
    assert model.asked == ["Company: Acme Labs\n\nBackend engineer, Python, 3 years"]
    assert job["side"] == "company" and job["step"] == "awaiting_posting"
    assert job["brief"]["role"] == "Backend Engineer" and job["brief"]["company"] == "Acme Labs"
    assert len(job["posting"]["questions"]) == 5 and job["posting"]["approved_at"] is None
    steps = [e.payload["step"] for e in c.app.state.db.list_events(job_id) if e.type == "step_changed"]
    assert steps == ["briefing", "writing", "awaiting_posting"]


def test_without_a_typed_role_a_role_brief_opens_in_english() -> None:
    c = client()
    job = c.post("/roles", json={"company": "Acme Labs"}).json()
    brief = job["conversations"][0]
    assert job["step"] == "briefing" and brief["kind"] == "role_brief" and brief["language"] == "en"
    record = c.app.state.db.get_conversation(brief["id"])["record"]
    assert record["shareable"] == {"company": "Acme Labs"}
    assert c.post(f"/jobs/{job['id']}/voice").json()["room"] == f"brief-{brief['id']}"


def test_hr_edits_then_approves_the_posting() -> None:
    c = client()
    job = c.get(f"/jobs/{c.post('/roles', json={'company': 'Acme', 'request': 'Backend engineer'}).json()['id']}").json()
    body = edit(job)
    body["questions"] = body["questions"][:3]
    body["job_description"] = "Edited by HR: you will build our APIs in Python."
    saved = c.put(f"/roles/{job['id']}/posting", json=body).json()
    assert len(saved["posting"]["questions"]) == 3 and saved["posting"]["job_description"].startswith("Edited")
    c.post(f"/roles/{job['id']}/posting/approve", json=body)
    approved = c.get(f"/jobs/{job['id']}").json()
    assert approved["step"] == "awaiting_approval" and approved["posting"]["approved_at"]
    # Once approved it cannot be changed or approved again.
    assert c.put(f"/roles/{job['id']}/posting", json=body).status_code == 409
    assert c.post(f"/roles/{job['id']}/posting/approve", json=body).status_code == 409


def test_bad_postings_are_refused() -> None:
    c = client()
    job = c.get(f"/jobs/{c.post('/roles', json={'company': 'Acme', 'request': 'Backend engineer'}).json()['id']}").json()
    body = edit(job)
    assert c.put(f"/roles/{job['id']}/posting", json={**body, "questions": []}).status_code == 422
    assert c.put(f"/roles/{job['id']}/posting", json={**body, "questions": [QUESTION] * 6}).status_code == 422
    assert c.put(f"/roles/{job['id']}/posting", json={**body, "job_description": "short"}).status_code == 422
    assert c.post("/roles", json={"company": "A"}).status_code == 422


def test_a_role_that_says_nothing_is_reported() -> None:
    c = client(FakeModel({**POSTING, "understood": False}))
    job = c.get(f"/jobs/{c.post('/roles', json={'company': 'Acme', 'request': 'hello'}).json()['id']}").json()
    assert job["status"] == "failed" and "what role" in job["error"] and job["posting"] is None


def approved_job(model: FakeModel) -> tuple[TestClient, dict]:
    c = client(model)
    job = c.get(f"/jobs/{c.post('/roles', json={'company': 'Acme', 'request': 'Data engineer'}).json()['id']}").json()
    c.post(f"/roles/{job['id']}/posting/approve", json=edit(job))
    return c, c.get(f"/jobs/{job['id']}").json()


def test_approving_the_posting_crawls_public_profiles_without_contact_details() -> None:
    model = FakeModel()
    c, job = approved_job(model)
    search = model.searched[0]
    assert search["tools"] == [{"type": "web_search"}] and "Backend Engineer (Python)" in search["input"]
    assert "Must have: Python, APIs" in search["input"]
    people = job["people"]
    assert [p["name"] for p in people] == ["Asha Rao", "Ravi Kumar"]  # duplicates, no link and no name dropped
    assert all(p["source"] == "web" and p["phone"] is None and not p["approved"] for p in people)
    assert people[0]["profile_url"] == "https://in.linkedin.com/in/asha-rao" and people[1]["company"] == ""
    assert "source_url" not in people[0]  # the source page is not kept
    assert job["step"] == "awaiting_approval" and job["search"]["sourced"]["found"] == 2
    steps = [e.payload["step"] for e in c.app.state.db.list_events(job["id"]) if e.type == "step_changed"]
    assert steps[-2:] == ["sourcing", "awaiting_approval"]


def test_a_failed_search_does_not_fail_the_job() -> None:
    _, job = approved_job(FakeModel(search_fails=True))
    assert job["status"] == "active" and job["step"] == "awaiting_approval" and job["people"] == []
    assert "did not work" in job["search"]["sourced"]["error"]


def test_a_home_job_has_no_posting_endpoints() -> None:
    from backend.tests.test_jobs import START
    c = client()
    home = c.post("/jobs", json=START).json()["id"]
    assert c.put(f"/roles/{home}/posting", json=edit({"posting": {**POSTING, "questions": [QUESTION]}})).status_code == 404
