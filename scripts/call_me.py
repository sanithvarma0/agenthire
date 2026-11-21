"""Development only: place a home-side test call to one of the builder's own numbers.

The call goes through the back end's real dialling and guardrails
(`POST /dev/test-call`, available only in test mode). Needs the back end and
the voice worker running.

    .venv\\Scripts\\python scripts\\call_me.py --language te \\
        --work "the fan and a few switches in one room are not working" --area "Whitefields, HITEC City"

After the call it prints the transcript and the result written from it.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend.db import Database  # noqa: E402
from backend.guardrails import ground_call_result  # noqa: E402
from backend.models import ConversationRecord, Language  # noqa: E402
from backend.settings import get_settings  # noqa: E402
from backend.writers.call_result import transcript_from_events, write_call_result  # noqa: E402
from voice.text_mode import openai_client  # noqa: E402

WAIT_FOR_END_SECONDS = 300


def watch_stream(base: str, job_id: str, arrivals: dict[int, float]) -> None:
    """Read the job's server-sent events and note when each one arrives."""
    try:
        with httpx.stream("GET", f"{base}/events/stream", params={"job_id": job_id},
                          timeout=httpx.Timeout(10, read=WAIT_FOR_END_SECONDS)) as response:
            for line in response.iter_lines():
                if line.startswith("id: "):
                    arrivals[int(line[4:])] = time.time()
    except Exception as exc:  # the call report still prints without the stream
        print(f"stream watcher stopped: {type(exc).__name__}: {exc}", flush=True)


def report_stream(events: list, arrivals: dict[int, float]) -> None:
    """Compare what reached the live stream with what was stored."""
    stored = [e.seq for e in events]
    missing = [s for s in stored if s not in arrivals]
    order = [s for s in sorted(arrivals, key=arrivals.get)]
    delays = sorted(arrivals[e.seq] - datetime.fromisoformat(e.created_at).timestamp()
                    for e in events if e.seq in arrivals)
    live = [d for d in delays if d < 5]  # events stored before the watcher connected came by replay
    print(f"\n--- live stream: {len(arrivals)} of {len(stored)} events arrived; missing {missing or 'none'}; "
          f"in order: {order == sorted(order)}")
    if live:
        print(f"    delay from stored to arrival: median {statistics.median(live) * 1000:.0f} ms, "
              f"max {max(live) * 1000:.0f} ms ({len(live)} live events)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default=(settings.allowed_numbers or [""])[0])
    parser.add_argument("--language", default="te", choices=[lang.value for lang in Language])
    parser.add_argument("--calling", required=True, help="The business or person to ask for, e.g. a shop name")
    parser.add_argument("--work", required=True)
    parser.add_argument("--area", required=True, help="Colony and locality, e.g. 'Knowledge City, Raidurg'")
    parser.add_argument("--when", default="tomorrow")
    args = parser.parse_args()

    base = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
    response = httpx.post(f"{base}/dev/test-call", timeout=30, json={
        "to": args.to, "language": args.language, "calling": args.calling, "work": args.work, "area": args.area, "when": args.when})
    response.raise_for_status()
    placed = response.json()
    job_id, conversation_id = placed["job_id"], placed["conversation_id"]
    if placed["refused"]:
        sys.exit(f"The back end refused the call: {placed['refused']}")
    print(f"job {job_id}, conversation {conversation_id}: ringing; watching the live stream...", flush=True)

    # Watch the same live stream the web app will use, and time each event's arrival.
    arrivals: dict[int, float] = {}
    watcher = threading.Thread(target=watch_stream, args=(base, job_id, arrivals), daemon=True)
    watcher.start()

    db = Database(settings.database_path)
    started = time.time()
    while time.time() - started < WAIT_FOR_END_SECONDS:
        if any(e.type == "conversation_ended" for e in db.list_events(job_id, conversation_id=conversation_id)):
            break
        time.sleep(2)
    time.sleep(2)  # let the last events reach the stream
    events = db.list_events(job_id, conversation_id=conversation_id)
    report_stream(db.list_events(job_id), arrivals)

    print("\n--- transcript and events")
    for e in events:
        if e.type in ("agent_said", "person_said"):
            extra = f"  ({e.payload['response_ms']} ms)" if "response_ms" in e.payload else ""
            print(f"[{e.seq}] {e.type.split('_')[0]:6} {e.payload['text']}{extra}")
        elif e.type != "tool_called":
            print(f"[{e.seq}] {e.type} {json.dumps(e.payload, ensure_ascii=False)}")

    transcript = transcript_from_events(events)
    record = ConversationRecord(**db.get_conversation(conversation_id)["record"])
    result = write_call_result(record, transcript, client=openai_client(settings), settings=settings,
                               now=datetime.now())
    result, problems = ground_call_result(result, transcript)
    print(f"\n--- result: {result.outcome.value}, do-not-call {result.do_not_call}, language {result.language_spoken}")
    for fact in result.facts:
        print(f"{'OK ' if fact.verified else 'NOT CONFIRMED'} {fact.name} = {fact.value}  [{fact.said_as}]")
    if result.notes:
        print(f"notes: {result.notes}")
    if problems:
        print("problems:", problems)


if __name__ == "__main__":
    main()
