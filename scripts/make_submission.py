"""Build the submission zip: every committed file, plus any extra files named (the demo
video, the slides). Only committed files go in, so .env, databases and logs never do.

Run from the repository root, after committing:

    python scripts/make_submission.py [--add <file> ...] [--env-for-judges] [--out agenthire-submission.zip]

--env-for-judges puts the builder's own .env into the zip as .env.example, with working
keys for the judges (the builder's decision, 22 Nov 2026; the keys are rotated after the
event). It never touches git: the committed .env.example stays blank, because the
repository is public. The zip's copy gets its own LiveKit agent name, so a judge's worker
and the builder's never take each other's calls.

Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEVER = (".env", ".db", ".sqlite", ".sqlite3", ".pem", ".log")
REQUIRED = ("AGENTS.md", "README.md", ".env.example")
JUDGES_AGENT_NAME = "agenthire-judges"
JUDGES_HEADER = """# Working keys for judging Builders 2026, provided by the builder.
# Rename this file to .env (cp .env.example .env). These keys are rotated after the event.
# TEST_MODE stays true: every call and SMS goes to DEMO_ROUTE_PHONE, the builder's phone.
# To answer the calls yourself, put your own number (with country code) in DEMO_ROUTE_PHONE
# and add it to ALLOWED_NUMBERS.

"""


def env_for_judges() -> str:
    """The builder's .env with its own agent name, in the template's order of keys."""
    env = (ROOT / ".env").read_text(encoding="utf-8").replace("\r\n", "\n")
    lines, seen = [], False
    for line in env.split("\n"):
        key = line.split("=", 1)[0].strip()
        if key in ("AGENT_NAME", "INTERNAL_API_TOKEN"):
            if key == "AGENT_NAME":
                lines.append(f"AGENT_NAME={JUDGES_AGENT_NAME}")
                seen = True
            else:
                lines.append("INTERNAL_API_TOKEN=")
            continue
        lines.append(line)
    if not seen:
        lines.append(f"AGENT_NAME={JUDGES_AGENT_NAME}")
    text = "\n".join(lines).rstrip("\n") + "\n"
    if "TEST_MODE=true" not in text.replace(" ", ""):
        sys.exit("Refusing: the judges' .env must have TEST_MODE=true.")
    return JUDGES_HEADER + text


def committed_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    return [name for name in out.decode("utf-8").split("\0") if name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--add", action="append", default=[], help="An extra file to include, such as the demo video or the slides")
    parser.add_argument("--env-for-judges", action="store_true", help="Ship the builder's .env as .env.example (working keys)")
    parser.add_argument("--out", default="agenthire-submission.zip")
    args = parser.parse_args()

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    if dirty.strip():
        print("Note: there are uncommitted changes; only committed files go in.")

    files = committed_files()
    for name in REQUIRED:
        if name not in files:
            sys.exit(f"Missing {name}: commit it first.")
    bad = [f for f in files if f.endswith(NEVER) and not f.endswith(".env.example")]
    if bad:
        sys.exit(f"Refusing: these must never be shipped: {bad}")

    extras = [Path(p).resolve() for p in args.add]
    for extra in extras:
        if not extra.is_file():
            sys.exit(f"Not a file: {extra}")
        if extra.name.endswith(NEVER):
            sys.exit(f"Refusing to add {extra.name}")

    has_video = any(e.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv") for e in extras)
    video_md = (ROOT / "VIDEO.md").read_text(encoding="utf-8") if (ROOT / "VIDEO.md").exists() else ""
    if not has_video and ("VIDEO_LINK_HERE" in video_md or not video_md):
        print("Warning: no video file added and VIDEO.md has no link yet.")
    has_slides = any(e.suffix.lower() in (".pdf", ".pptx") for e in extras) or any(
        f.lower().endswith((".pdf", ".pptx")) and "slides" in f.lower() for f in files)
    if not has_slides:
        print("Warning: no slides (.pdf or .pptx) added.")

    judges_env = env_for_judges() if args.env_for_judges else None
    out = (ROOT / args.out).resolve()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in files:
            if name == ".env.example" and judges_env is not None:
                z.writestr("agenthire/.env.example", judges_env)
            else:
                z.write(ROOT / name, f"agenthire/{name}")
        for extra in extras:
            z.write(extra, f"agenthire/{extra.name}")
    size = out.stat().st_size / 1_000_000
    print(f"Wrote {out.name}: {len(files)} committed files + {len(extras)} extra, {size:.1f} MB")
    if judges_env is not None:
        print(f".env.example in the zip holds working keys (agent name {JUDGES_AGENT_NAME}); "
              "do not share this zip anywhere else, and rotate the keys after the event.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
