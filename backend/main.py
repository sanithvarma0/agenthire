"""The AgentHire back end.

Run with:  .venv\\Scripts\\python -m uvicorn backend.main:create_app --factory --port 8000

`create_app` is a factory so that importing this module opens no database;
tests build their own app around an in-memory database.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend import conversations, dev, events, providers
from backend.calls import Dialler, LiveKitDialler
from backend.db import Database
from backend.events import EventBus
from backend.jobs import api as jobs_api
from backend.jobs import roles
from backend.settings import Settings, get_settings


def create_app(settings: Settings | None = None, database: Database | None = None,
               dialler: Dialler | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = database or Database(settings.database_path)

    app = FastAPI(title="AgentHire")
    app.state.settings = settings
    app.state.db = db
    app.state.bus = EventBus(db)
    app.state.dialler = dialler or LiveKitDialler(settings)
    app.include_router(events.router)
    app.include_router(conversations.router)
    app.include_router(dev.router)
    app.include_router(providers.router)
    app.include_router(jobs_api.router)
    app.include_router(roles.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
