"""Conversation endpoints. The voice worker fetches its conversation record here
(docs/HLD.md, layer rules: the worker reaches data only through the back end)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter()


def check_internal_token(request: Request, token: str | None) -> None:
    expected = request.app.state.settings.secrets.internal_api_token
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="missing or wrong internal token")


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request,
                     x_internal_token: str | None = Header(default=None)) -> dict[str, Any]:
    check_internal_token(request, x_internal_token)
    conversation = request.app.state.db.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="no such conversation")
    return conversation
