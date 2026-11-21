"""SQLite storage for AgentHire.

One file, six tables (docs/LLD.md, section 4). Objects are stored as JSON text
and returned as plain dictionaries or the typed objects from models.py.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.models import Event, JobStep, Person, Side

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    side        TEXT NOT NULL,
    step        TEXT NOT NULL,
    status      TEXT NOT NULL,
    brief       TEXT,
    start       TEXT,
    search      TEXT,
    report      TEXT,
    error       TEXT,
    posting     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
    id            TEXT PRIMARY KEY,
    job_id        TEXT NOT NULL REFERENCES jobs(id),
    role          TEXT NOT NULL,
    name          TEXT NOT NULL,
    phone         TEXT,
    source        TEXT NOT NULL,
    rating        REAL,
    review_count  INTEGER,
    address       TEXT,
    distance_km   REAL,
    approved      INTEGER NOT NULL DEFAULT 0,
    raw           TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    person_id   TEXT REFERENCES people(id),
    kind        TEXT NOT NULL,
    language    TEXT NOT NULL,
    record      TEXT NOT NULL,
    status      TEXT NOT NULL,
    started_at  TEXT,
    ended_at    TEXT,
    result      TEXT,
    routed_to   TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL REFERENCES jobs(id),
    conversation_id  TEXT REFERENCES conversations(id),
    seq              INTEGER NOT NULL,
    type             TEXT NOT NULL,
    payload          TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE (job_id, seq)
);
CREATE TABLE IF NOT EXISTS facts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type            TEXT NOT NULL,
    subject_key             TEXT NOT NULL,
    key                     TEXT NOT NULL,
    value                   TEXT NOT NULL,
    source_conversation_id  TEXT,
    updated_at              TEXT NOT NULL,
    UNIQUE (subject_type, subject_key, key)
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    person_id   TEXT REFERENCES people(id),
    channel     TEXT NOT NULL,
    to_address  TEXT NOT NULL,
    routed_to   TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _load(text: str | None) -> Any:
    return json.loads(text) if text else None


class Database:
    """A thin wrapper over one SQLite connection.

    The app is single-user and runs one job at a time, so one connection
    guarded by a lock is enough.
    """

    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            # Columns added after a database file may already exist.
            columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(conversations)")}
            if "routed_to" not in columns:
                self._conn.execute("ALTER TABLE conversations ADD COLUMN routed_to TEXT")
            job_columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(jobs)")}
            for column in ("start", "search", "report", "error", "posting"):
                if column not in job_columns:
                    self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")

    def close(self) -> None:
        self._conn.close()

    def _write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # --- jobs ---------------------------------------------------------------

    def create_job(self, side: Side, start: dict[str, Any] | None = None) -> str:
        """A new job. `start` is what the Start screen sent (language, address, location)."""
        job_id, stamp = new_id("job"), now()
        self._write(
            "INSERT INTO jobs (id, side, step, status, start, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, side, JobStep.BRIEFING, "active",
             json.dumps(start, ensure_ascii=False) if start is not None else None, stamp, stamp),
        )
        return job_id

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not rows:
            return None
        return self._job(rows[0])

    def list_jobs(self, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC" + (" LIMIT ?" if limit else "")
        return [self._job(r) for r in self._rows(sql, (limit,) if limit else ())]

    @staticmethod
    def _job(row: sqlite3.Row) -> dict[str, Any]:
        return {**dict(row), "brief": _load(row["brief"]), "start": _load(row["start"]),
                "search": _load(row["search"]), "report": _load(row["report"]), "posting": _load(row["posting"])}

    def set_job_step(self, job_id: str, step: JobStep, status: str = "active") -> None:
        self._write(
            "UPDATE jobs SET step = ?, status = ?, updated_at = ? WHERE id = ?",
            (step, status, now(), job_id),
        )

    def set_job_search(self, job_id: str, search: dict[str, Any]) -> None:
        """Where and how far the providers were searched for (area, radius)."""
        self._write("UPDATE jobs SET search = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(search, ensure_ascii=False), now(), job_id))

    def set_job_report(self, job_id: str, report: dict[str, Any]) -> None:
        """The comparison and recommendation, and later which provider the user picked."""
        self._write("UPDATE jobs SET report = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(report, ensure_ascii=False), now(), job_id))

    def set_job_error(self, job_id: str, error: str) -> None:
        """A step could not go on; the web app shows the reason."""
        self._write("UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                    (error, now(), job_id))

    def set_job_posting(self, job_id: str, posting: dict[str, Any]) -> None:
        """A company job's job description, screening questions and scoring guide."""
        self._write("UPDATE jobs SET posting = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(posting, ensure_ascii=False), now(), job_id))

    def set_job_brief(self, job_id: str, brief: dict[str, Any]) -> None:
        self._write(
            "UPDATE jobs SET brief = ?, updated_at = ? WHERE id = ?",
            (json.dumps(brief, ensure_ascii=False), now(), job_id),
        )

    # --- people -------------------------------------------------------------

    def add_person(self, person: Person, raw: dict[str, Any] | None = None) -> None:
        self._write(
            "INSERT INTO people (id, job_id, role, name, phone, source, rating, review_count, address,"
            " distance_km, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (person.id, person.job_id, person.role, person.name, person.phone, person.source,
             person.rating, person.review_count, person.address, person.distance_km,
             json.dumps(raw, ensure_ascii=False) if raw is not None else None),
        )

    def list_people(self, job_id: str, approved_only: bool = False) -> list[Person]:
        sql = "SELECT * FROM people WHERE job_id = ?" + (" AND approved = 1" if approved_only else "")
        return [Person(**{k: r[k] for k in Person.model_fields}) for r in self._rows(sql + " ORDER BY rowid", (job_id,))]

    def people_view(self, job_id: str) -> list[dict[str, Any]]:
        """People in rank order with everything the screens show (map position, open now,
        whether approved). The finder's extra details live in `raw`."""
        out = []
        for r in self._rows("SELECT * FROM people WHERE job_id = ? ORDER BY rowid", (job_id,)):
            person = {k: r[k] for k in Person.model_fields}
            out.append({**(_load(r["raw"]) or {}), **person, "approved": bool(r["approved"])})
        return out

    def get_person(self, person_id: str) -> Person | None:
        rows = self._rows("SELECT * FROM people WHERE id = ?", (person_id,))
        return Person(**{k: rows[0][k] for k in Person.model_fields}) if rows else None

    def approve_people(self, job_id: str, person_ids: list[str]) -> None:
        """Record exactly which people the user approved for calling."""
        self._write("UPDATE people SET approved = 0 WHERE job_id = ?", (job_id,))
        for person_id in person_ids:
            self._write("UPDATE people SET approved = 1 WHERE job_id = ? AND id = ?", (job_id, person_id))

    def is_approved(self, job_id: str, phone: str) -> bool:
        rows = self._rows(
            "SELECT 1 FROM people WHERE job_id = ? AND phone = ? AND approved = 1", (job_id, phone)
        )
        return bool(rows)

    # --- conversations ------------------------------------------------------

    def create_conversation(self, job_id: str, kind: str, language: str, record: dict[str, Any],
                            person_id: str | None = None) -> str:
        conversation_id = new_id("conv")
        self._write(
            "INSERT INTO conversations (id, job_id, person_id, kind, language, record, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, job_id, person_id, kind, language, json.dumps(record, ensure_ascii=False), "pending"),
        )
        return conversation_id

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        if not rows:
            return None
        conversation = dict(rows[0])
        conversation["record"] = _load(conversation["record"])
        conversation["result"] = _load(conversation["result"])
        return conversation

    def list_conversations(self, job_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT id FROM conversations WHERE job_id = ?", [job_id]
        if kind:
            sql, params = sql + " AND kind = ?", params + [kind]
        return [self.get_conversation(r["id"]) for r in self._rows(sql + " ORDER BY rowid", tuple(params))]

    def set_conversation_status(self, conversation_id: str, status: str) -> None:
        stamp = now()
        column = {"active": "started_at", "ended": "ended_at"}.get(status)
        if column:
            self._write(
                f"UPDATE conversations SET status = ?, {column} = ? WHERE id = ?", (status, stamp, conversation_id)
            )
        else:
            self._write("UPDATE conversations SET status = ? WHERE id = ?", (status, conversation_id))

    def set_conversation_routed_to(self, conversation_id: str, number: str) -> None:
        """Record that this call rang the builder's phone instead of the provider's."""
        self._write("UPDATE conversations SET routed_to = ? WHERE id = ?", (number, conversation_id))

    def set_conversation_result(self, conversation_id: str, result: dict[str, Any]) -> None:
        self._write(
            "UPDATE conversations SET result = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=False), conversation_id),
        )

    def count_calls(self, job_id: str, kind: str) -> int:
        """Calls that were actually started for a job; blocked ones do not count."""
        rows = self._rows(
            "SELECT COUNT(*) AS n FROM conversations WHERE job_id = ? AND kind = ? AND status != 'blocked'",
            (job_id, kind),
        )
        return rows[0]["n"]

    # --- events -------------------------------------------------------------

    def add_event(self, job_id: str, type: str, payload: dict[str, Any],
                  conversation_id: str | None = None) -> Event:
        """Append to a job's stream. Sequence numbers are per job and never reused."""
        stamp, body = now(), json.dumps(payload, ensure_ascii=False)
        with self._lock, self._conn:
            seq = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            cursor = self._conn.execute(
                "INSERT INTO events (job_id, conversation_id, seq, type, payload, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, conversation_id, seq, type, body, stamp),
            )
        return Event(id=cursor.lastrowid, job_id=job_id, conversation_id=conversation_id, seq=seq,
                     type=type, payload=payload, created_at=stamp)

    def list_events(self, job_id: str, after_seq: int = 0, conversation_id: str | None = None) -> list[Event]:
        sql, params = "SELECT * FROM events WHERE job_id = ? AND seq > ?", [job_id, after_seq]
        if conversation_id:
            sql, params = sql + " AND conversation_id = ?", params + [conversation_id]
        return [
            Event(id=r["id"], job_id=r["job_id"], conversation_id=r["conversation_id"], seq=r["seq"],
                  type=r["type"], payload=json.loads(r["payload"]), created_at=r["created_at"])
            for r in self._rows(sql + " ORDER BY seq", tuple(params))
        ]

    # --- facts (long-term memory) -------------------------------------------

    def set_fact(self, subject_type: str, subject_key: str, key: str, value: str,
                 source_conversation_id: str | None = None) -> None:
        self._write(
            "INSERT INTO facts (subject_type, subject_key, key, value, source_conversation_id, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (subject_type, subject_key, key) DO UPDATE SET"
            " value = excluded.value, source_conversation_id = excluded.source_conversation_id,"
            " updated_at = excluded.updated_at",
            (subject_type, subject_key, key, value, source_conversation_id, now()),
        )

    def get_facts(self, subject_type: str, subject_key: str) -> dict[str, str]:
        rows = self._rows(
            "SELECT key, value FROM facts WHERE subject_type = ? AND subject_key = ?", (subject_type, subject_key)
        )
        return {r["key"]: r["value"] for r in rows}

    # --- messages -----------------------------------------------------------

    def add_message(self, job_id: str, channel: str, to_address: str, routed_to: str, body: str,
                    status: str, person_id: str | None = None) -> int:
        cursor = self._write(
            "INSERT INTO messages (job_id, person_id, channel, to_address, routed_to, body, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, person_id, channel, to_address, routed_to, body, status, now()),
        )
        return cursor.lastrowid

    def list_messages(self, job_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows("SELECT * FROM messages WHERE job_id = ? ORDER BY id", (job_id,))]
