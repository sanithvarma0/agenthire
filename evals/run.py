"""Run the home-side eval scenarios (docs/LLD.md, section 16).

Each run is a full text-mode conversation between the AgentHire agent and a
model playing the provider, followed by the same result writer and grounding
check used after a real call. Then the run is checked against the scenario.

    .venv\\Scripts\\python -m evals.run                 # every scenario, 3 runs each
    .venv\\Scripts\\python -m evals.run --only busy_te --runs 1

A scenario passes when at least 2 of its runs pass. A summary is written to
evals/last_run.md, so the numbers can be quoted.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from backend.guardrails import ground_call_result
from backend.writers.brief import BriefNotUnderstood, write_brief
from backend.models import CallResult, Event, Language, TranscriptLine
from backend.settings import Settings, get_settings
from backend.text_match import words
from voice.engine.speech_text import has_leaked_tool_text, same_question, unspeakable_characters
from backend.writers.call_result import transcript_from_events, write_call_result
from backend.models import FactSpec
from voice.engine.kinds import build_record
from voice.text_mode import TextConversation, openai_client

EVALS_DIR = Path(__file__).resolve().parent
SCENARIOS_PATH = EVALS_DIR / "scenarios.yaml"
MAX_TURNS = 12
HANG_UP = "<hangs up>"

PERSONA_RULES = """You are on a phone call; someone is calling you about a job. Reply only with the words you
say aloud, in {language}, in short spoken sentences, one or two at a time. Write {language} in its own script,
as a speech transcript would, keeping English words in English letters. Answer what you are asked and do
not volunteer everything at once. Stay on the line until the caller says goodbye; only then reply with
exactly {hang_up} and nothing else.

Who you are:
{persona}"""

# For the voice brief the model plays the user, talking to the assistant in the app.
USER_RULES = """You are using a voice assistant in an app to get something fixed at your home. Reply only with the
words you say aloud, in {language}, in short spoken sentences, one or two at a time. Write {language} in its own
script, as a speech transcript would, keeping English words in English letters. Answer what you are asked. Only
after the assistant has read back your problem and you have said it is right, and it then says goodbye, reply
with exactly {hang_up} and nothing else.

Who you are:
{persona}"""


@dataclass
class RunReport:
    scenario: str
    run: int
    passed: bool
    failures: list[str]
    transcript: list[TranscriptLine]
    result: CallResult | None
    seconds: float
    end_reason: str | None = None
    notes: list[str] = field(default_factory=list)


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- checks -----------------------------------------------------------------

_NATIVE = {
    Language.TELUGU: re.compile(f"[{chr(0x0C00)}-{chr(0x0C7F)}]"),
    Language.HINDI: re.compile(f"[{chr(0x0900)}-{chr(0x097F)}]"),
}
_MENTIONS_AI = re.compile(r"\b(AI|A\.I\.|assistant|robot|bot)\b", re.IGNORECASE)
_UNSPEAKABLE = re.compile(r"[/\\*#\[\]{}<>]")


def check_result(expect: dict[str, Any], result: CallResult, today: datetime) -> list[str]:
    """What is wrong with the written, grounded result, compared with the scenario."""
    failures = []
    if result.outcome.value != expect["outcome"]:
        failures.append(f"outcome is {result.outcome.value}, expected {expect['outcome']}")
    for name, rule in (expect.get("facts") or {}).items():
        fact = result.fact(name)
        if fact is None:
            failures.append(f"{name} is missing")
            continue
        if fact.verified is not True:
            failures.append(f"{name} is not confirmed by the transcript")
        if "equals" in rule and fact.value.strip().lower() != str(rule["equals"]).lower():
            failures.append(f"{name} is {fact.value!r}, expected {rule['equals']!r}")
        if "contains" in rule and str(rule["contains"]) not in fact.value:
            failures.append(f"{name} is {fact.value!r}, expected it to contain {rule['contains']!r}")
        if "date_offset" in rule:
            wanted = (today + timedelta(days=int(rule["date_offset"]))).strftime("%Y-%m-%d")
            if wanted not in fact.value:
                failures.append(f"{name} is {fact.value!r}, expected the date {wanted}")
    for name in expect.get("absent") or []:
        if result.fact(name) is not None:
            failures.append(f"{name} should not be in the result, but is {result.fact(name).value!r}")
    if "language_spoken" in expect and (result.language_spoken is None
                                        or result.language_spoken.value != expect["language_spoken"]):
        failures.append(f"language_spoken is {result.language_spoken}, expected {expect['language_spoken']}")
    unconfirmed = [f.name for f in result.facts if f.verified is False and f.name not in (expect.get("facts") or {})]
    if unconfirmed:
        failures.append(f"unconfirmed facts: {', '.join(unconfirmed)}")
    return failures


def _same_question(first: list[str], second: list[str]) -> bool:
    return same_question(" ".join(first), " ".join(second))


def _questions(text: str) -> list[list[str]]:
    """The words of each question in a line (the text before each question mark, back to the last stop)."""
    found = []
    for part in text.split("?")[:-1]:
        sentence = re.split(r"[.!" + chr(0x0964) + "]", part)[-1]
        if words(sentence):
            found.append(words(sentence))
    return found


def _last_question(text: str) -> list[str]:
    questions = _questions(text)
    return questions[-1] if questions else []


def _repeats_itself(text: str) -> bool:
    """Whether a line asks the same question twice, as when two model replies were joined."""
    questions = _questions(text)
    return any(_same_question(a, b) for i, a in enumerate(questions) for b in questions[i + 1:])


def check_language(transcript: list[TranscriptLine], language: Language, switch_to: Language | None) -> list[str]:
    """After the person first speaks, the agent must speak `switch_to` if given,
    or stay in the call's language. The opening comes before they speak, so it is not checked."""
    first_person = next((t.seq for t in transcript if t.speaker == "person"), None)
    if first_person is None:
        return []
    wanted = switch_to or language
    if wanted not in _NATIVE:
        return []
    later = [t for t in transcript if t.speaker == "agent" and t.seq > first_person]
    wrong = [t.seq for t in later if not _NATIVE[wanted].search(t.text)]
    if wrong:
        name = {Language.TELUGU: "Telugu", Language.HINDI: "Hindi"}[wanted]
        return [f"lines {wrong}: not in {name}" + (" after the person spoke it" if switch_to else "")]
    return []


def check_brief(expect: dict[str, Any], service: str, work: str) -> list[str]:
    """The brief written from a voice-brief transcript, compared with the scenario."""
    failures = []
    if "service_contains" in expect and expect["service_contains"].lower() not in service.lower():
        failures.append(f"service is {service!r}, expected it to contain {expect['service_contains']!r}")
    if "work_contains" in expect and expect["work_contains"].lower() not in work.lower():
        failures.append(f"work is {work!r}, expected it to contain {expect['work_contains']!r}")
    return failures


def check_conduct(transcript: list[TranscriptLine], language: Language, end_reason: str | None,
                  may_say_ai: bool = False) -> list[str]:
    """Rules about how the agent spoke, checked on its own lines. In the voice brief the
    agent is the user's own assistant, so saying so is fine (`may_say_ai`)."""
    failures = []
    agent_lines = [t for t in transcript if t.speaker == "agent"]
    person_lines = [t for t in transcript if t.speaker == "person"]
    if not agent_lines:
        return ["the agent never spoke"]
    asked_about_ai = any(_MENTIONS_AI.search(t.text) for t in person_lines)
    for line in agent_lines:
        if _MENTIONS_AI.search(line.text) and not asked_about_ai and not may_say_ai:
            failures.append(f"line {line.seq}: mentions being an AI without being asked")
        if _UNSPEAKABLE.search(line.text) or unspeakable_characters(line.text):
            failures.append(f"line {line.seq}: contains characters a voice cannot speak")
        if has_leaked_tool_text(line.text):
            failures.append(f"line {line.seq}: speaks a tool call out loud")
    for line in agent_lines:
        if _repeats_itself(line.text):
            failures.append(f"line {line.seq}: says the same thing twice")
    for earlier, later in zip(agent_lines, agent_lines[1:]):
        if _same_question(_last_question(earlier.text), _last_question(later.text)):
            failures.append(f"line {later.seq}: ends with the same question as line {earlier.seq}")
    if language in _NATIVE:
        allowed = [pattern for pattern in _NATIVE.values()]  # switching to the other Indian language is fine
        wrong = [t.seq for t in agent_lines if not any(p.search(t.text) for p in allowed)]
        if wrong:
            failures.append(f"lines {wrong}: written only in English letters")
    if end_reason in (None, "time cap reached", "turn limit reached"):
        failures.append(f"the conversation did not end properly ({end_reason or 'still open'})")
    return failures


# --- one run ----------------------------------------------------------------

def persona_reply(client: Any, settings: Settings, scenario: dict[str, Any],
                  history: list[dict[str, str]]) -> str:
    rules = USER_RULES if scenario["kind"] == "brief" else PERSONA_RULES
    system = rules.format(language=scenario["persona_language"], hang_up=HANG_UP, persona=scenario["persona"].strip())
    # The larger model plays the provider: the smaller one drifted out of character,
    # for example writing Hindi in English letters, which real speech-to-text does not do.
    response = client.chat.completions.create(
        model=settings.secrets.llm_model_smart, reasoning_effort="low",
        messages=[{"role": "system", "content": system}, *history],
    )
    return (response.choices[0].message.content or "").strip()


def run_once(scenario: dict[str, Any], run: int, client: Any, settings: Settings, today: datetime) -> RunReport:
    started = time.time()
    events: list[Event] = []

    def emit(type_, payload) -> None:
        events.append(Event(id=len(events) + 1, job_id="eval", conversation_id="eval", seq=len(events) + 1,
                            type=type_.value, payload=payload, created_at=""))

    language = Language(scenario["language"])
    # A screening scenario lists its approved questions; they become answer_1, answer_2...
    # as on a real screening call (backend/jobs/calling.py, screening_record).
    questions = [FactSpec(name=f"answer_{i}", description=f"Their answer to screening question {i}: {q}")
                 for i, q in enumerate(scenario.get("questions", []), start=1)]
    record = build_record(scenario["kind"], language,
                          time_cap_seconds=settings.calling.time_cap_seconds,
                          wrap_up_at_seconds=settings.calling.wrap_up_at_seconds,
                          shareable=scenario["job"], extra_facts=questions)
    convo = TextConversation(record, settings=settings, client=client, emit=emit)
    history: list[dict[str, str]] = []
    agent_line = convo.start()
    for _ in range(scenario.get("max_turns", MAX_TURNS)):
        if convo.ended:
            break
        history.append({"role": "user", "content": agent_line})
        said = persona_reply(client, settings, scenario, history)
        if not said or HANG_UP in said:
            convo.close("the provider hung up")
            break
        history.append({"role": "assistant", "content": said})
        agent_line = convo.reply(said) or ""
    else:
        convo.close("turn limit reached")

    transcript = transcript_from_events(events)
    switch_to = scenario["expect"].get("agent_switches_to")
    if scenario["kind"] == "brief":
        said = "\n".join(f"{'USER' if t.speaker == 'person' else 'AGENT'}: {t.text}" for t in transcript)
        try:
            brief = write_brief(said, client=client, settings=settings)
            failures = check_brief(scenario["expect"].get("brief", {}), brief.service, brief.work)
            notes = [f"brief: {brief.service} / {brief.work}"]
        except BriefNotUnderstood:
            failures, notes = ["the brief writer could not tell what needs fixing"], []
        failures += (check_conduct(transcript, language, convo.state.end_reason, may_say_ai=True)
                     + check_language(transcript, language, Language(switch_to) if switch_to else None))
        return RunReport(scenario=scenario["id"], run=run, passed=not failures, failures=failures,
                         transcript=transcript, result=None, seconds=time.time() - started,
                         end_reason=convo.state.end_reason, notes=notes)
    result = write_call_result(record, transcript, client=client, settings=settings, now=today,
                               live=convo.state.live_result())
    result, _ = ground_call_result(result, transcript)
    failures = (check_result(scenario["expect"], result, today)
                + check_conduct(transcript, language, convo.state.end_reason)
                + check_language(transcript, language, Language(switch_to) if switch_to else None))
    return RunReport(scenario=scenario["id"], run=run, passed=not failures, failures=failures,
                     transcript=transcript, result=result, seconds=time.time() - started,
                     end_reason=convo.state.end_reason)


# --- report -----------------------------------------------------------------

def write_report(reports: list[RunReport], scenarios: list[dict[str, Any]], path: Path, started: datetime) -> str:
    lines = [f"# Eval results, {started:%a %d %b %Y %H:%M}", "",
             "| Scenario | Runs passed | Result |", "|---|---|---|"]
    for scenario in scenarios:
        runs = [r for r in reports if r.scenario == scenario["id"]]
        passed = sum(r.passed for r in runs)
        lines.append(f"| {scenario['id']}: {scenario['description']} | {passed} of {len(runs)} | "
                     f"{'pass' if passed * 3 >= len(runs) * 2 else 'FAIL'} |")
    lines += ["", "## Runs", ""]
    for report in reports:
        status = "pass" if report.passed else "FAIL"
        result = report.result
        facts = ", ".join(f"{f.name}={f.value}{'' if f.verified else ' (not confirmed)'}"
                          for f in (result.facts if result else []))
        lines.append(f"### {report.scenario}, run {report.run}: {status} ({report.seconds:.0f} s)")
        lines.append(f"- Outcome: {result.outcome.value if result else 'none'}; facts: {facts or 'none'}; "
                     f"language: {result.language_spoken.value if result and result.language_spoken else '-'}; "
                     f"ended: {report.end_reason}")
        for note in report.notes:
            lines.append(f"- Note: {note}")
        for failure in report.failures:
            lines.append(f"- Failure: {failure}")
        lines.append("")
        lines.append("```text")
        lines += [f"[{t.seq}] {t.speaker}: {t.text}" for t in report.transcript]
        lines.append("```")
        lines.append("")
    text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run AgentHire's eval scenarios.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", action="append", help="Run only this scenario id (repeatable)")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    settings = get_settings()
    client = openai_client(settings)
    scenarios = [s for s in load_scenarios() if not args.only or s["id"] in args.only]
    started = datetime.now()
    jobs = [(s, run) for s in scenarios for run in range(1, args.runs + 1)]

    def run_job(job: tuple[dict[str, Any], int]) -> RunReport:
        scenario, run = job
        try:
            return run_once(scenario, run, client, settings, started)
        except Exception as exc:  # one broken run must not stop the others
            return RunReport(scenario=scenario["id"], run=run, passed=False,
                             failures=[f"error: {type(exc).__name__}: {exc}"], transcript=[], result=None, seconds=0)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        reports = list(pool.map(run_job, jobs))

    for report in reports:
        mark = "pass" if report.passed else "FAIL"
        print(f"{report.scenario:14} run {report.run}: {mark:4} ({report.seconds:.0f} s)"
              + ("".join(f"\n      - {f}" for f in report.failures)))
    summary = write_report(reports, scenarios, EVALS_DIR / "last_run.md", started)
    print("\n" + "\n".join(summary.splitlines()[:3 + len(scenarios) + 1]))
    failed = [s["id"] for s in scenarios
              if sum(r.passed for r in reports if r.scenario == s["id"]) * 3 < args.runs * 2]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
