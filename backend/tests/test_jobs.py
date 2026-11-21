"""Tests for the job endpoints, the finding step and the Start screen's location lookup.
Google and the model are faked, so nothing goes over the network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from backend.db import Database
from backend.main import create_app
from backend.settings import load_settings

START = {"language": "te", "address": "Flat 302, 30/C, Knowledge City Rd, Madhapur, Hyderabad",
         "lat": 17.4325, "lng": 78.3798, "area": "Knowledge City, Madhapur, Hyderabad"}


class NoDialler:
    """Rings nobody; opens browser rooms for the voice brief, as LiveKit would."""

    def __init__(self):
        self.rooms: list[str] = []

    async def dial(self, **kwargs):  # pragma: no cover - nothing here dials
        raise AssertionError("no call should be placed")

    async def open_room(self, *, room, metadata):
        self.rooms.append(room)

    def browser_token(self, *, room, identity):
        return f"token-for-{room}"


class FakeModel:
    """Answers the brief writer with a fixed brief and keeps what it was asked."""

    def __init__(self, service: str = "electrician", work: str = "Kitchen light flickers.", understood: bool = True):
        self.answer = {"service": service, "work": work, "understood": understood}
        self.asked: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.asked.append(kwargs["messages"][-1]["content"])
        message = SimpleNamespace(content=json.dumps(self.answer), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def place(pid: str, name: str, km_north: float, rating: float = 4.5, reviews: int = 50) -> dict:
    return {"id": pid, "displayName": {"text": name}, "rating": rating, "userRatingCount": reviews,
            "internationalPhoneNumber": f"+91 90000 0000{pid[-1]}",
            "location": {"latitude": START["lat"] + km_north / 111.0, "longitude": START["lng"]},
            "businessStatus": "OPERATIONAL", "currentOpeningHours": {"openNow": True},
            "shortFormattedAddress": f"{name} road", "googleMapsUri": f"https://maps.google.com/?cid={pid}"}


def fake_google(places: list[dict]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocode" in request.url.path:
            if "neighborhood" in request.url.params.get("result_type", ""):
                return httpx.Response(200, json={"results": [{"address_components": [
                    {"long_name": "Indira Nagar", "types": ["neighborhood"]},
                    {"long_name": "Gachibowli", "types": ["sublocality_level_1", "sublocality"]},
                    {"long_name": "Hyderabad", "types": ["locality"]}]}]})
            return httpx.Response(200, json={"results": [
                {"formatted_address": "C9V2+JWV, 12, Road No 3, Indira Nagar, Gachibowli, Hyderabad, Telangana 500032, India"}]})
        return httpx.Response(200, json={"places": places})

    return httpx.Client(transport=httpx.MockTransport(handler))


def client(places: list[dict] | None = None, model: FakeModel | None = None) -> TestClient:
    app = create_app(settings=load_settings(), database=Database(":memory:"), dialler=NoDialler())
    app.state.http = fake_google(places or [])
    app.state.openai = model or FakeModel()
    return TestClient(app)


FIVE = [place("p1", "Far Good", 4.0, rating=4.9, reviews=400), place("p2", "Near Okay", 0.5, rating=4.2, reviews=30),
        place("p3", "Mid Good", 1.5, rating=4.7, reviews=120), place("p4", "Near Good", 0.8, rating=4.6, reviews=90),
        place("p5", "Mid Few", 2.5, rating=4.0, reviews=5)]


def test_a_job_without_a_request_opens_a_voice_brief() -> None:
    c = client()
    job = c.post("/jobs", json=START).json()
    assert job["step"] == "briefing" and job["side"] == "home" and job["test_mode"] is True
    assert job["people"] == [] and job["messages"] == []
    brief = job["conversations"][0]
    assert brief["kind"] == "brief" and brief["language"] == "te" and brief["status"] == "active"
    assert c.app.state.dialler.rooms == [f"brief-{brief['id']}"]  # a room in the browser, no phone rung
    access = c.post(f"/jobs/{job['id']}/voice").json()
    assert access["room"] == f"brief-{brief['id']}" and access["token"] == f"token-for-{access['room']}"
    assert c.get(f"/jobs/{job['id']}").json()["start"]["address"] == START["address"]
    events = c.app.state.db.list_events(job["id"])
    assert [e.type for e in events] == ["step_changed"] and events[0].payload == {"step": "briefing"}


def test_a_typed_request_is_understood_and_providers_are_found_best_first() -> None:
    model = FakeModel()
    c = client(FIVE, model)
    job_id = c.post("/jobs", json={**START, "request": "kitchen light flickers"}).json()["id"]
    job = c.get(f"/jobs/{job_id}").json()
    assert model.asked == ["kitchen light flickers"]
    assert job["brief"]["service"] == "electrician" and job["step"] == "awaiting_approval"
    names = [p["name"] for p in job["people"]]
    # Nearness and good reviews win: the two nearest well-reviewed come first, the far one is not on top.
    assert names[:2] == ["Near Good", "Mid Good"] and len(names) == 5
    first = job["people"][0]
    assert first["lat"] and first["lng"] and first["open_now"] is True and first["approved"] is False
    assert job["search"]["radius_km"] == 5 and job["search"]["call_top"] == 2
    steps = [e.payload["step"] for e in c.app.state.db.list_events(job_id) if e.type == "step_changed"]
    assert steps == ["briefing", "finding", "awaiting_approval"]


def test_a_request_that_says_nothing_is_reported_not_searched() -> None:
    c = client(FIVE, FakeModel(understood=False))
    job = c.get(f"/jobs/{c.post('/jobs', json={**START, 'request': 'hello'}).json()['id']}").json()
    assert job["status"] == "failed" and "describe the problem" in job["error"] and job["people"] == []


def test_no_providers_found_is_reported() -> None:
    c = client([])
    job = c.get(f"/jobs/{c.post('/jobs', json={**START, 'request': 'fan'}).json()['id']}").json()
    assert job["status"] == "failed" and job["error"].startswith("No electrician")


def test_approving_marks_who_to_call_and_moves_to_calling() -> None:
    c = client(FIVE)
    job = c.get(f"/jobs/{c.post('/jobs', json={**START, 'request': 'fan'}).json()['id']}").json()
    ids = [p["id"] for p in job["people"]]
    assert c.post(f"/jobs/{job['id']}/approve", json={"person_ids": ids[:3]}).status_code == 422  # at most 2
    assert c.post(f"/jobs/{job['id']}/approve", json={"person_ids": ["per_other"]}).status_code == 422
    after = c.post(f"/jobs/{job['id']}/approve", json={"person_ids": [ids[0], ids[3]]}).json()  # a swap
    assert after["step"] == "calling"
    assert [p["approved"] for p in after["people"]] == [True, False, False, True, False]
    assert c.post(f"/jobs/{job['id']}/approve", json={"person_ids": ids[:1]}).status_code == 409


def test_recent_jobs_are_newest_first() -> None:
    c = client()
    first = c.post("/jobs", json=START).json()["id"]
    second = c.post("/jobs", json=START).json()["id"]
    assert [j["id"] for j in c.get("/jobs").json()] == [second, first]


def test_history_says_how_each_job_ended() -> None:
    from backend.models import Person, PersonRole, Side
    c = client()
    db = c.app.state.db
    job_id = db.create_job(Side.HOME, start=START)
    for pid, name in [("per_a", "Sri Sai Electricals"), ("per_b", "Ravi Electric Works"), ("per_c", "Third Shop")]:
        db.add_person(Person(id=pid, job_id=job_id, role=PersonRole.PROVIDER, name=name, source="places"))
    for pid, outcome in [("per_a", "available"), ("per_b", "not_available")]:
        conv = db.create_conversation(job_id, "home_call", "te", {}, person_id=pid)
        db.set_conversation_result(conv, {"outcome": outcome, "facts": [], "notes": ""})
    db.create_conversation(job_id, "confirm_call", "te", {}, person_id="per_a")  # not counted as a call around
    db.set_job_report(job_id, {"booking": {"person_id": "per_a", "visit_time": "2026-11-23T10:00",
                                           "visiting_charge": "300", "address": "Flat 1"}})
    db.set_job_step(job_id, "done")
    failed = c.post("/jobs", json=START).json()["id"]
    db.set_job_error(failed, "No electrician found within 5 km.")
    db.set_job_step(failed, "finding", status="failed")

    done, gone = c.get("/jobs", params={"limit": 50}).json()[1], c.get("/jobs", params={"limit": 50}).json()[0]
    assert done["id"] == job_id and done["step"] == "done"
    assert (done["found"], done["called"], done["available"]) == (3, 2, 1)
    assert done["booked"] == {"name": "Sri Sai Electricals", "visit_time": "2026-11-23T10:00", "visiting_charge": "300"}
    assert gone["id"] == failed and gone["status"] == "failed" and gone["error"].startswith("No electrician")
    assert gone["booked"] is None and gone["language"] == "te"
    assert len(c.get("/jobs", params={"limit": 1}).json()) == 1
    assert c.get("/jobs", params={"limit": 0}).status_code == 422


def test_development_test_call_jobs_are_not_listed() -> None:
    from backend.models import Side
    c = client()
    c.app.state.db.create_job(Side.HOME)  # as /dev/test-call makes them: no start
    shown = c.post("/jobs", json=START).json()["id"]
    assert [j["id"] for j in c.get("/jobs").json()] == [shown]


def test_bad_start_requests_are_refused() -> None:
    c = client()
    assert c.post("/jobs", json={**START, "language": "fr"}).status_code == 422
    assert c.post("/jobs", json={**START, "address": ""}).status_code == 422
    assert c.post("/jobs", json={**START, "lat": 123}).status_code == 422
    assert c.get("/jobs/job_missing").status_code == 404


def test_the_location_gives_the_area_and_a_street_address() -> None:
    body = client().get("/location", params={"lat": 17.44, "lng": 78.35}).json()
    assert body["area"] == {"colony": "Indira Nagar", "locality": "Gachibowli", "city": "Hyderabad"}
    assert body["street_address"] == "12, Road No 3, Indira Nagar, Gachibowli, Hyderabad, Telangana 500032"
