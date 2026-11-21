"""Finds real local providers near the user with Google Places (docs/LLD.md, section 12).

The user's location comes from the browser, as Google Maps does it. The search
uses the user's own words for the service ("electrician", "AC repair",
"carpenter"), so no trade is listed in code. Results without a phone number, or
permanently closed, are dropped; the rest are ranked with places open now first,
then by nearness, rating and number of reviews (weights in config.yaml). If fewer than `min_results`
are within the search radius, the search widens once.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel

from backend.guardrails import normalise_phone
from backend.settings import Settings

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
FIELDS = ",".join("places." + f for f in (
    "id", "displayName", "internationalPhoneNumber", "rating", "userRatingCount", "location",
    "shortFormattedAddress", "businessStatus", "primaryType", "currentOpeningHours.openNow", "googleMapsUri",
))
PLUS_CODE = re.compile(r"^[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,3},\s*")
ATTEMPTS = 3  # the venue network drops connections, and Places refused requests just after billing was linked


class Provider(BaseModel):
    place_id: str
    name: str
    phone: str
    rating: float | None = None
    review_count: int = 0
    distance_km: float
    lat: float = 0.0   # for the map
    lng: float = 0.0
    address: str = ""
    open_now: bool | None = None
    primary_type: str = ""
    maps_url: str = ""


class Area(BaseModel):
    colony: str = ""  # the neighbourhood, e.g. "Knowledge City"; the user can correct it in the web app
    locality: str     # e.g. "Gachibowli"
    city: str

    @property
    def spoken(self) -> str:
        """Colony, locality and city, without repeats. The agent names the colony and locality."""
        parts: list[str] = []
        for part in (self.colony, self.locality, self.city):
            if part and part not in parts:
                parts.append(part)
        return ", ".join(parts)


class Location(BaseModel):
    """Where the user is, from one reverse-geocoding call: the area the agent names on
    calls, and a street address the user completes with the house or flat number."""
    area: Area
    street_address: str = ""


class SearchResult(BaseModel):
    area: Area
    radius_km: float
    providers: list[Provider]


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance on the Earth's surface (haversine)."""
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _request(http: httpx.Client, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            response = http.request(method, url, **kwargs)
            if response.status_code in (403, 429) or response.status_code >= 500:
                raise httpx.HTTPStatusError(f"HTTP {response.status_code}: {response.text[:200]}",
                                            request=response.request, response=response)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Google request failed after {ATTEMPTS} attempts: {last}")


def area_at(lat: float, lng: float, *, settings: Settings, http: httpx.Client) -> Area:
    """The colony, locality and city at a point, for the agent to name on the call.

    Asks only for area-level results: an unfiltered lookup named the wrong area for a
    point in Gachibowli, because its street-level results carried other names."""
    data = _request(http, "GET", GEOCODE_URL, params={
        "latlng": f"{lat},{lng}", "key": settings.secrets.google_maps_api_key,
        "result_type": "neighborhood|sublocality|locality", "language": "en"})
    colony = locality = city = ""
    for result in data.get("results", []):
        parts = {t: c["long_name"] for c in result.get("address_components", []) for t in c.get("types", [])}
        colony = colony or parts.get("neighborhood") or parts.get("sublocality_level_2") or ""
        locality = locality or parts.get("sublocality_level_1") or parts.get("sublocality") or ""
        city = city or parts.get("locality", "")
    return Area(colony=colony, locality=locality or city or "", city=city)


def street_at(lat: float, lng: float, *, settings: Settings, http: httpx.Client) -> str:
    """The nearest street-level address, for the user to complete with the house number."""
    data = _request(http, "GET", GEOCODE_URL, params={
        "latlng": f"{lat},{lng}", "key": settings.secrets.google_maps_api_key,
        "result_type": "street_address|premise|route", "language": "en"})
    results = data.get("results", [])
    street = results[0].get("formatted_address", "").removesuffix(", India") if results else ""
    # Google sometimes leads with a plus code ("C9V2+JWV, ..."), which nobody would say.
    return PLUS_CODE.sub("", street)


def location_at(lat: float, lng: float, *, settings: Settings, http: httpx.Client) -> Location:
    """Where the user is: the area named on calls and a street address to complete."""
    return Location(area=area_at(lat, lng, settings=settings, http=http),
                    street_address=street_at(lat, lng, settings=settings, http=http))


def _search(service: str, lat: float, lng: float, radius_km: float, *, settings: Settings,
            http: httpx.Client) -> list[Provider]:
    data = _request(http, "POST", PLACES_URL, headers={
        "X-Goog-Api-Key": settings.secrets.google_maps_api_key, "X-Goog-FieldMask": FIELDS,
    }, json={
        "textQuery": service, "pageSize": 20, "languageCode": "en",
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                    "radius": min(radius_km * 1000, 50000.0)}},
    })
    providers = []
    for place in data.get("places", []):
        phone = normalise_phone(place.get("internationalPhoneNumber", ""))
        location = place.get("location") or {}
        if not phone or place.get("businessStatus") == "CLOSED_PERMANENTLY" or "latitude" not in location:
            continue
        providers.append(Provider(
            place_id=place.get("id", ""), name=(place.get("displayName") or {}).get("text", ""), phone=phone,
            rating=place.get("rating"), review_count=place.get("userRatingCount", 0),
            distance_km=round(distance_km(lat, lng, location["latitude"], location["longitude"]), 2),
            lat=location["latitude"], lng=location["longitude"],
            address=place.get("shortFormattedAddress", ""),
            open_now=(place.get("currentOpeningHours") or {}).get("openNow"),
            primary_type=place.get("primaryType", ""), maps_url=place.get("googleMapsUri", ""),
        ))
    return providers


def rank(providers: list[Provider], radius_km: float, settings: Settings) -> list[Provider]:
    """Best first: open now, then a weighted score of nearness, rating and review count."""
    weights = settings.providers.ranking_weights
    most_reviews = max((p.review_count for p in providers), default=0)

    def score(p: Provider) -> float:
        rating = (p.rating or 0) / 5
        reviews = math.log1p(p.review_count) / math.log1p(most_reviews) if most_reviews else 0
        nearness = max(0.0, 1 - p.distance_km / radius_km)
        return weights.rating * rating + weights.review_count * reviews + weights.distance * nearness

    return sorted(providers, key=lambda p: (p.open_now is True, score(p)), reverse=True)


def find_providers(service: str, lat: float, lng: float, *, settings: Settings,
                   http: httpx.Client | None = None) -> SearchResult:
    """Real providers for `service` near the user, best first, at most `max_shown`."""
    rules = settings.providers
    own_http = http is None
    http = http or httpx.Client(timeout=15)
    try:
        area = area_at(lat, lng, settings=settings, http=http)
        found: dict[str, Provider] = {}
        radius = rules.search_radius_km
        for radius in (rules.search_radius_km, rules.wider_radius_km):
            for p in _search(service, lat, lng, radius, settings=settings, http=http):
                found.setdefault(p.place_id or p.phone, p)
            within = [p for p in found.values() if p.distance_km <= radius]
            if len(within) >= rules.min_results:
                break
        providers = [p for p in found.values() if p.distance_km <= radius]
        # One listing per phone number: the same person is sometimes listed twice.
        unique: dict[str, Provider] = {}
        for p in rank(providers, radius, settings):
            unique.setdefault(p.phone, p)
        return SearchResult(area=area, radius_km=radius, providers=list(unique.values())[: rules.max_shown])
    finally:
        if own_http:
            http.close()
