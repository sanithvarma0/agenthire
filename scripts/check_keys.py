"""Check that each key in .env works.

Uses only the Python standard library, so it runs before anything is installed.
Prints a status line per service and never prints a key or secret.

Run from the repository root:  python scripts/check_keys.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_SECONDS = 25
ATTEMPTS = 3  # the network may drop connections, so every request is retried


def load_env(path: Path) -> None:
    """Read KEY=value lines from .env into the environment."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def report(ok: bool | None, name: str, detail: str) -> None:
    label = {True: "OK     ", False: "FAIL   ", None: "UNKNOWN"}[ok]
    print(f"{label} {name}: {detail}", flush=True)


def missing(*names: str) -> list[str]:
    return [n for n in names if not os.getenv(n)]


def request(method: str, url: str, headers: dict[str, str] | None = None, body: dict | None = None):
    """Return (status, parsed JSON or text). Retries on network errors only."""
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(headers or {})
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
    last_error: Exception | None = None
    for attempt in range(ATTEMPTS):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            last_error = err
            time.sleep(1 + attempt)
            continue
        text = raw.decode("utf-8", errors="replace")
        try:
            return status, json.loads(text)
        except json.JSONDecodeError:
            return status, text
    raise ConnectionError(f"no response after {ATTEMPTS} attempts: {last_error}")


def basic_auth(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def short(value: object, limit: int = 200) -> str:
    return str(value)[:limit]


def check_openai() -> None:
    if missing("OPENAI_API_KEY"):
        return report(False, "OpenAI", "OPENAI_API_KEY is empty")
    status, body = request(
        "GET", "https://api.openai.com/v1/models",
        {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
    )
    if status != 200:
        return report(False, "OpenAI", f"HTTP {status}: {short(body)}")
    ids = sorted(m["id"] for m in body["data"])
    report(True, "OpenAI", f"{len(ids)} models visible")
    # Listed so the model names in .env can be chosen from what this key can use.
    tags = ("gpt-5", "realtime", "transcribe", "tts", "search")
    print("        relevant models: " + ", ".join(i for i in ids if any(t in i for t in tags)))


def check_twilio() -> None:
    if miss := missing("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"):
        return report(False, "Twilio", f"empty: {', '.join(miss)}")
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth = basic_auth(sid, os.environ["TWILIO_AUTH_TOKEN"])
    base = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"

    status, body = request("GET", f"{base}.json", auth)
    if status != 200:
        return report(False, "Twilio", f"HTTP {status}: {short(body)}")
    report(True, "Twilio account", f"status={body.get('status')}, type={body.get('type')}")

    status, body = request("GET", f"{base}/Balance.json", auth)
    if status == 200:
        report(True, "Twilio balance", f"{body.get('balance')} {body.get('currency')}")
    else:
        report(None, "Twilio balance", f"HTTP {status}")

    number = urllib.parse.quote(os.environ["TWILIO_PHONE_NUMBER"])
    status, body = request("GET", f"{base}/IncomingPhoneNumbers.json?PhoneNumber={number}", auth)
    numbers = body.get("incoming_phone_numbers", []) if status == 200 else []
    if numbers:
        caps = numbers[0].get("capabilities", {})
        report(True, "Twilio number", f"owned; voice={caps.get('voice')}, sms={caps.get('sms')}")
    else:
        report(False, "Twilio number", "the number in .env is not on this account")

    status, body = request("GET", "https://voice.twilio.com/v1/DialingPermissions/Countries/IN", auth)
    if status == 200:
        enabled = body.get("low_risk_numbers_enabled")
        report(bool(enabled), "Twilio calls to India", f"low_risk_numbers_enabled={enabled}")
    else:
        report(None, "Twilio calls to India", f"HTTP {status}")

    status, body = request("GET", "https://trunking.twilio.com/v1/Trunks", auth)
    if status == 200:
        trunks = body.get("trunks", [])
        names = ", ".join(f"{t.get('friendly_name')} ({t.get('domain_name')})" for t in trunks) or "none"
        report(True, "Twilio SIP trunks", f"{len(trunks)} found: {names}")
    else:
        report(None, "Twilio SIP trunks", f"HTTP {status}")


def check_sarvam() -> None:
    if missing("SARVAM_API_KEY"):
        return report(False, "Sarvam", "SARVAM_API_KEY is empty")
    status, body = request(
        "POST", "https://api.sarvam.ai/text-lid",
        {"api-subscription-key": os.environ["SARVAM_API_KEY"]},
        {"input": "నాకు ఒక ఎలక్ట్రీషియన్ కావాలి"},
    )
    if status == 200 and isinstance(body, dict):
        report(True, "Sarvam", f"language detected: {body.get('language_code')}, script: {body.get('script_code')}")
    elif status in (401, 403):
        report(False, "Sarvam", f"key rejected (HTTP {status})")
    else:
        report(None, "Sarvam", f"HTTP {status}: {short(body)}")


def livekit_token(grants: dict) -> str:
    """Sign a short-lived LiveKit access token (HS256 JWT) by hand."""
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"iss": os.environ["LIVEKIT_API_KEY"], "nbf": now - 10, "exp": now + 300, **grants}
    payload = b64(json.dumps(claims).encode())
    signature = hmac.new(
        os.environ["LIVEKIT_API_SECRET"].encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{b64(signature)}"


def check_livekit() -> None:
    if miss := missing("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        return report(False, "LiveKit", f"empty: {', '.join(miss)}")
    host = os.environ["LIVEKIT_URL"].replace("wss://", "https://").replace("ws://", "http://").rstrip("/")

    def call(service: str, method: str, grants: dict):
        headers = {"Authorization": f"Bearer {livekit_token(grants)}"}
        return request("POST", f"{host}/twirp/livekit.{service}/{method}", headers, {})

    status, body = call("RoomService", "ListRooms", {"video": {"roomList": True}})
    if status != 200:
        return report(False, "LiveKit", f"HTTP {status}: {short(body)}")
    report(True, "LiveKit", f"connected; {len(body.get('rooms', []))} active rooms")

    sip = {"sip": {"admin": True, "call": True}}
    for label, method in (("outbound trunks", "ListSIPOutboundTrunk"), ("inbound trunks", "ListSIPInboundTrunk"),
                          ("dispatch rules", "ListSIPDispatchRule")):
        status, body = call("SIP", method, sip)
        if status != 200:
            report(None, f"LiveKit SIP {label}", f"HTTP {status}: {short(body)}")
            continue
        items = body.get("items", [])
        report(True, f"LiveKit SIP {label}", f"{len(items)} found")
        for item in items:
            trunk_id = item.get("sip_trunk_id") or item.get("sipTrunkId") or item.get("sip_dispatch_rule_id") or item.get("sipDispatchRuleId")
            print(f"          id={trunk_id} name={item.get('name')!r} numbers={item.get('numbers')} address={item.get('address')}")


def check_hindsight() -> None:
    if missing("HINDSIGHT_API_KEY"):
        return report(None, "Hindsight", "HINDSIGHT_API_KEY is empty (optional)")
    base = os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io").rstrip("/")
    status, body = request(
        "GET", f"{base}/v1/default/banks",
        {"Authorization": f"Bearer {os.environ['HINDSIGHT_API_KEY']}"},
    )
    if status == 200:
        banks = body.get("banks", body) if isinstance(body, dict) else body
        report(True, "Hindsight", f"key accepted; {len(banks)} memory banks")
    elif status in (401, 403):
        report(False, "Hindsight", f"key rejected (HTTP {status})")
    else:
        report(None, "Hindsight", f"HTTP {status} from the banks endpoint: {short(body)}")


def check_google() -> None:
    if missing("GOOGLE_MAPS_API_KEY"):
        return report(None, "Google Places", "GOOGLE_MAPS_API_KEY is empty (not set up yet)")
    status, body = request(
        "POST", "https://places.googleapis.com/v1/places:searchText",
        {"X-Goog-Api-Key": os.environ["GOOGLE_MAPS_API_KEY"], "X-Goog-FieldMask": "places.displayName"},
        {"textQuery": "electrician in Raidurg Hyderabad", "pageSize": 1},
    )
    if status == 200:
        report(True, "Google Places", f"{len(body.get('places', []))} result returned")
    else:
        report(False, "Google Places", f"HTTP {status}: {short(body, 300)}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_env(ROOT / ".env")
    for check in (check_openai, check_twilio, check_sarvam, check_livekit, check_hindsight, check_google):
        try:
            check()
        except Exception as exc:  # report and continue with the other services
            report(False, check.__name__.removeprefix("check_"), f"{type(exc).__name__}: {short(exc)}")


if __name__ == "__main__":
    main()
