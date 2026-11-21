"""Provider search endpoint. The web app sends the service the user asked for and
the location from the browser; the back end finds real providers nearby."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import httpx

from backend.finders.places import Location, SearchResult, find_providers, location_at

router = APIRouter()


@router.get("/location")
def location(lat: float, lng: float, request: Request) -> Location:
    """The area named on calls and a street address, for the Start screen to prefill."""
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(status_code=422, detail="latitude or longitude out of range")
    http = getattr(request.app.state, "http", None)
    try:
        if http is not None:
            return location_at(lat, lng, settings=request.app.state.settings, http=http)
        with httpx.Client(timeout=15) as own:
            return location_at(lat, lng, settings=request.app.state.settings, http=own)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class ProviderSearch(BaseModel):
    service: str = Field(min_length=2, max_length=120, description="In the user's own words")
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@router.post("/providers/search")
def search(body: ProviderSearch, request: Request) -> SearchResult:
    try:
        return find_providers(body.service, body.lat, body.lng, settings=request.app.state.settings,
                              http=getattr(request.app.state, "http", None))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
