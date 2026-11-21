"""Tests for the Places finder, with Google's answers faked (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.finders.places import distance_km, find_providers
from backend.settings import load_settings

USER = (17.4325, 78.3798)  # the venue, Raidurg


def place(pid: str, name: str, phone: str | None, km_north: float, rating: float = 4.5, reviews: int = 50,
          open_now: bool | None = True, status: str = "OPERATIONAL") -> dict:
    p = {"id": pid, "displayName": {"text": name}, "rating": rating, "userRatingCount": reviews,
         "location": {"latitude": USER[0] + km_north / 111.0, "longitude": USER[1]},
         "businessStatus": status, "currentOpeningHours": {"openNow": open_now},
         "shortFormattedAddress": f"{name} road", "googleMapsUri": f"https://maps.google.com/?cid={pid}"}
    if phone:
        p["internationalPhoneNumber"] = phone
    return p


def fake_google(places_by_radius: dict[float, list[dict]], *, fail_first: int = 0):
    """A transport that answers geocoding and Places like Google does."""
    calls = {"places": [], "fail": fail_first}

    def handler(request: httpx.Request) -> httpx.Response:
        if "geocode" in request.url.path:
            return httpx.Response(200, json={"results": [{"address_components": [
                {"long_name": "HITEC City", "types": ["sublocality_level_1", "sublocality"]},
                {"long_name": "Hyderabad", "types": ["locality"]}]}]})
        if calls["fail"]:
            calls["fail"] -= 1
            return httpx.Response(403, json={"error": "permission denied"})
        body = json.loads(request.content)
        radius = body["locationBias"]["circle"]["radius"] / 1000
        calls["places"].append({"query": body["textQuery"], "radius_km": radius})
        return httpx.Response(200, json={"places": places_by_radius.get(radius, [])})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_distance_is_measured_on_the_ground() -> None:
    assert distance_km(*USER, USER[0] + 1 / 111.0, USER[1]) == pytest.approx(1.0, abs=0.01)


def test_providers_are_filtered_ranked_and_capped() -> None:
    places = [
        place("a", "No Phone Electricals", None, 1),
        place("b", "Closed Electricals", "+91 90000 00002", 1, status="CLOSED_PERMANENTLY"),
        place("c", "Far Electricals", "+91 90000 00003", 7),
        place("d", "Good Near", "+91 90000 00004", 0.5, rating=4.9, reviews=300),
        place("e", "Closed Now", "+91 90000 00005", 0.3, rating=5.0, reviews=500, open_now=False),
        place("f", "Okay Near", "+91 90000 00006", 2, rating=4.0, reviews=10),
        place("g", "Duplicate Of D", "+91 90000 00004", 0.6, rating=4.0, reviews=5),
    ]
    http, calls = fake_google({5.0: places})
    result = find_providers("electrician", *USER, settings=load_settings(), http=http)
    names = [p.name for p in result.providers]
    assert "No Phone Electricals" not in names and "Closed Electricals" not in names
    assert "Far Electricals" not in names              # beyond 5 km
    assert names.count("Good Near") == 1 and "Duplicate Of D" not in names  # one listing per number
    assert names[0] == "Good Near"                     # open now and best scored
    assert names[-1] == "Closed Now"                   # not open now ranks after those that are
    assert result.providers[0].phone == "+919000000004"
    assert result.area.spoken == "HITEC City, Hyderabad"
    assert calls["places"] == [{"query": "electrician", "radius_km": 5.0}]  # enough found, no widening


def test_the_area_names_the_colony_when_google_has_one() -> None:
    from backend.finders.places import area_at

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {"address_components": [{"long_name": "Knowledge City", "types": ["neighborhood", "political"]},
                                    {"long_name": "Raidurg", "types": ["sublocality_level_1", "sublocality"]},
                                    {"long_name": "Hyderabad", "types": ["locality"]}]},
            {"address_components": [{"long_name": "Raidurg", "types": ["sublocality_level_1", "sublocality"]},
                                    {"long_name": "Hyderabad", "types": ["locality"]}]}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    area = area_at(*USER, settings=load_settings(), http=http)
    assert (area.colony, area.locality, area.city) == ("Knowledge City", "Raidurg", "Hyderabad")
    assert area.spoken == "Knowledge City, Raidurg, Hyderabad"


def test_the_search_widens_when_too_few_are_near() -> None:
    near = [place("a", "Only Near", "+91 90000 00001", 1)]
    wider = near + [place("b", "Wider One", "+91 90000 00002", 7), place("c", "Wider Two", "+91 90000 00003", 9),
                    place("d", "Too Far", "+91 90000 00004", 12)]
    http, calls = fake_google({5.0: near, 10.0: wider})
    result = find_providers("plumber", *USER, settings=load_settings(), http=http)
    assert [c["radius_km"] for c in calls["places"]] == [5.0, 10.0]
    assert result.radius_km == 10.0
    assert {p.name for p in result.providers} == {"Only Near", "Wider One", "Wider Two"}


def test_a_refused_request_is_retried() -> None:
    http, calls = fake_google({5.0: [place("a", "A", "+91 90000 00001", 1)] * 1}, fail_first=1)
    result = find_providers("electrician", *USER, settings=load_settings(), http=http)
    assert len(calls["places"]) >= 1 and result.providers


def test_the_service_words_are_the_users_own() -> None:
    http, calls = fake_google({5.0: []})
    find_providers("washing machine repair", *USER, settings=load_settings(), http=http)
    assert calls["places"][0]["query"] == "washing machine repair"


def test_the_endpoint_validates_the_location() -> None:
    from fastapi.testclient import TestClient
    from backend.db import Database
    from backend.main import create_app
    client = TestClient(create_app(settings=load_settings(), database=Database(":memory:")))
    assert client.post("/providers/search", json={"service": "electrician", "lat": 200, "lng": 78}).status_code == 422
    assert client.post("/providers/search", json={"service": "", "lat": 17, "lng": 78}).status_code == 422
