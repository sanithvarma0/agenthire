// Calls screen (docs/LLD.md, section 15). The call in progress fills the stage: who is being
// called, ringing then talking with a timer and waveform, facts as they are noted and the
// transcript as it happens; when it ends, the checked result (with the provider's own words)
// replaces the live notes. The rail shows the queue. Skip ends the call in progress; Stop
// calls no one else after it.

import { useEffect, useMemo, useState } from "react";
import { Ban, CheckCircle2, Clock, FlaskConical, IndianRupee, PhoneCall, PhoneOff, SkipForward, XCircle } from "lucide-react";
import { api, type CallResultView, type Conversation, type Job, type JobEvent, type Person } from "../api";
import { initials, JobLayout, StepRail } from "../components/Frame";
import { formatClock, formatRupees, formatWhen, GOOD_OUTCOMES, OUTCOME_LABELS } from "../format";
import { useJob } from "../store";
import { ListenLive } from "../components/ListenLive";
import { Transcript } from "./Brief";

const FACT_LABELS: Record<string, string> = {
  available: "Can come", earliest_time: "When", visiting_charge: "Charge", visit_time: "Visit time",
  interested: "Interested", expected_salary: "Expected salary", notice_period: "Notice",
};
const ENQUIRY_FACTS = ["available", "earliest_time", "visiting_charge"];

function factLabel(name: string): string {
  const question = name.match(/^answer_(\d+)$/);
  return question ? `Q${question[1]}` : FACT_LABELS[name] ?? name.replace(/_/g, " ");
}

/** The facts shown live on a screening call: interest, each question, salary and notice. */
export function screeningFacts(questions: number): string[] {
  return ["interested", ...Array.from({ length: questions }, (_, i) => `answer_${i + 1}`), "expected_salary", "notice_period"];
}

export function Calls({ job }: { job: Job }) {
  const events = useJob((s) => s.events);
  const company = job.side === "company";
  const approved = job.people.filter((p) => p.approved);
  const calls = job.conversations.filter((c) => c.kind === (company ? "screening_call" : "home_call"));
  const factNames = company ? screeningFacts(job.posting?.questions.length ?? 0) : ENQUIRY_FACTS;
  const stopping = events.some((e) => e.type === "step_changed" && e.payload.stopping);
  const active = calls.find((c) => c.status === "active");
  const shown = active ?? calls.at(-1) ?? null;
  const person = approved.find((p) => p.id === shown?.person_id) ?? approved[0];
  const reporting = job.step !== "calling";
  const [busy, setBusy] = useState<"skip" | "stop" | null>(null);

  const control = async (what: "skip" | "stop") => {
    setBusy(what);
    try {
      await (what === "skip" ? api.skip(job.id) : api.stop(job.id));
    } catch {
      /* the call may have just ended; the stream shows what happened */
    } finally {
      setBusy(null);
    }
  };

  const remaining = approved.length - calls.length;
  const stage = (
    <>
      {reporting && (
        <div className="notice warn"><Clock size={17} />All calls are done. {company ? "Scoring the answers…" : "Comparing the answers…"}</div>
      )}
      {person && <CallPanel person={person} conversation={shown} events={events} factNames={factNames} />}
      {!reporting && active && (
        <div className="controls">
          <button className="btn ghost" onClick={() => control("skip")} aria-busy={busy === "skip"}><SkipForward size={16} />Skip this one</button>
          {remaining > 0 && !stopping && (
            <button className="btn danger" onClick={() => control("stop")} aria-busy={busy === "stop"}><Ban size={16} />Stop after this</button>
          )}
        </div>
      )}
    </>
  );

  const rail = (
    <>
      <StepRail job={job} />
      <section className="panel tight">
        <div className="panel-head"><p className="eyebrow">Calls</p><span className="faint small">{company ? "One at a time" : "One at a time, best first"}</span></div>
        {approved.map((p, i) => {
          const conversation = calls.find((c) => c.person_id === p.id) ?? null;
          return <QueueRow key={p.id} person={p} order={i + 1} conversation={conversation} events={events} />;
        })}
        {stopping && !reporting && <p className="faint small" style={{ margin: "8px 0 0" }}>No more calls after this one.</p>}
      </section>
    </>
  );
  return <JobLayout stage={stage} rail={rail} />;
}

function QueueRow({ person, order, conversation, events }: {
  person: Person; order: number; conversation: Conversation | null; events: JobEvent[];
}) {
  const status = callStatus(conversation, events);
  const facts = factsOf(conversation?.result);
  return (
    <div className="qitem">
      <span className="rank" style={{ background: "var(--panel-raised)", color: "var(--text-2)" }}>{order}</span>
      <div className="who">
        <strong>{person.name}</strong>
        <span className="faint small">
          {conversation?.result && conversation.result.outcome === "available"
            ? [facts.earliest_time && formatWhen(facts.earliest_time), facts.visiting_charge && formatRupees(facts.visiting_charge)].filter(Boolean).join(" · ")
            : person.distance_km != null ? `${person.distance_km.toFixed(1)} km away` : person.headline ?? ""}
        </span>
      </div>
      <span className={`chip ${status.tone}`}>{status.label}</span>
    </div>
  );
}

/** The live or finished view of one call: used by the Calls and Confirming screens. */
export function CallPanel({ person, conversation, events, factNames = ENQUIRY_FACTS }: {
  person: Person; conversation: Conversation | null; events: JobEvent[]; factNames?: string[];
}) {
  const mine = useMemo(
    () => (conversation ? events.filter((e) => e.conversation_id === conversation.id) : []),
    [events, conversation],
  );
  const lines = mine.filter((e) => e.type === "agent_said" || e.type === "person_said");
  const blocked = mine.find((e) => e.type === "guardrail_blocked");
  const ended = mine.some((e) => e.type === "conversation_ended");
  const result = conversation?.result ?? null;
  const talkingSince = lines.length ? new Date(lines[0].created_at).getTime() : null;
  const status = callStatus(conversation, events);
  const live = !!conversation && !blocked && !result && !ended;
  const jobId = useJob((s) => s.jobId);

  return (
    <section className="panel call-hero fade-in" key={conversation?.id ?? person.id}>
      <div className="call-head">
        <span className={`avatar-sq ${live ? "live" : ""}`}>{initials(person.name)}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p className="title md" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{person.name}</p>
          <span className="faint small">{person.phone ?? person.headline ?? ""}{person.distance_km != null ? ` · ${person.distance_km.toFixed(1)} km away` : ""}</span>
        </div>
        <span className={`chip ${status.tone}`}>
          {live ? <PhoneCall size={13} /> : result ? (GOOD_OUTCOMES.has(result.outcome) ? <CheckCircle2 size={13} /> : <XCircle size={13} />) : <PhoneOff size={13} />}
          {status.label}{live && talkingSince && <> · <Timer since={talkingSince} /></>}
        </span>
      </div>

      {live && (
        <div className={`wave-big ${talkingSince ? "" : "quiet"}`} aria-hidden="true">
          {Array.from({ length: 40 }, (_, i) => <span key={i} style={{ animationDelay: `${(i * 83) % 900}ms` }} />)}
        </div>
      )}
      {live && conversation && jobId && <ListenLive jobId={jobId} conversationId={conversation.id} live={live} />}
      {conversation?.routed_to && (
        <span className="routed"><FlaskConical size={13} />{person.phone ? "Test mode: answered" : "No number, so this rang you: answered"} by you, not by {person.name}</span>
      )}
      {blocked && <div className="notice bad">{String(blocked.payload.reason ?? "This call was not placed.")}</div>}

      {result ? <Result result={result} /> : conversation && !blocked && <LiveFacts events={mine} names={factNames} />}

      {lines.length > 0 && (result ? (
        <details className="more"><summary>Show the conversation</summary><Transcript lines={lines} them={person.name} /></details>
      ) : (
        <Transcript lines={lines} them={person.name} />
      ))}
      {!conversation && <p className="faint" style={{ margin: 0 }}>Waiting to call…</p>}
    </section>
  );
}

function LiveFacts({ events, names }: { events: JobEvent[]; names: string[] }) {
  const noted: Record<string, string> = {};
  for (const e of events) if (e.type === "fact_recorded") noted[String(e.payload.name)] = String(e.payload.value);
  return (
    <div className="facts">
      {names.map((name) => (
        <span key={name} className={`fact ${noted[name] ? "got" : ""}`}>
          {noted[name] ? factText(name, noted[name]) : `${factLabel(name)}…`}
        </span>
      ))}
    </div>
  );
}

function Result({ result }: { result: CallResultView }) {
  const facts = factsOf(result);
  const quotes = uniqueQuotes(result.facts.filter((f) => f.verified !== false));
  return (
    <div className="stack">
      {result.outcome === "interested" ? (
        <div className="facts">
          {result.facts.filter((f) => f.verified !== false).map((f) => (
            <span key={f.name} className="fact got">{factLabel(f.name)}: {f.value}</span>
          ))}
        </div>
      ) : result.outcome === "available" ? (
        <div className="numbers">
          <div className="num"><span><Clock size={12} />When</span><strong>{facts.earliest_time || facts.visit_time ? formatWhen(facts.earliest_time ?? facts.visit_time) : "Not said"}</strong></div>
          <div className="num"><span><IndianRupee size={12} />Visit</span><strong>{facts.visiting_charge ? formatRupees(facts.visiting_charge) : "Not said"}</strong></div>
          <div className="num"><span><CheckCircle2 size={12} />Outcome</span><strong className="plain">{OUTCOME_LABELS[result.outcome]}</strong></div>
        </div>
      ) : (
        <div className="notice bad"><XCircle size={17} />{OUTCOME_LABELS[result.outcome] ?? result.outcome}</div>
      )}
      {quotes.map((q) => <p key={q} className="quote">“{q}”</p>)}
      {result.notes && <p className="faint small" style={{ margin: 0 }}>{result.notes}</p>}
    </div>
  );
}

export function callStatus(conversation: Conversation | null, events: JobEvent[]): { label: string; tone: string } {
  if (!conversation) return { label: "Next", tone: "" };
  const mine = events.filter((e) => e.conversation_id === conversation.id);
  if (mine.some((e) => e.type === "guardrail_blocked")) return { label: "Not called", tone: "bad" };
  const result = conversation.result;
  if (result) return { label: OUTCOME_LABELS[result.outcome] ?? result.outcome, tone: GOOD_OUTCOMES.has(result.outcome) ? "good" : "bad" };
  if (mine.some((e) => e.type === "conversation_ended")) return { label: "Writing up…", tone: "" };
  if (mine.some((e) => e.type === "agent_said" || e.type === "person_said")) return { label: "Talking", tone: "good" };
  return { label: "Ringing…", tone: "warn" };
}

export function factsOf(result: CallResultView | null | undefined): Record<string, string> {
  return Object.fromEntries((result?.facts ?? []).filter((f) => f.verified !== false).map((f) => [f.name, f.value]));
}

/** The provider's words behind the facts, each once (one sentence often gives two facts). */
export function uniqueQuotes(facts: { said_as: string }[]): string[] {
  return [...new Set(facts.map((f) => f.said_as.trim()).filter(Boolean))];
}

export function factText(name: string, value: string): string {
  if (name === "available") return value.toLowerCase() === "yes" ? "Can come" : "Can't come";
  if (name === "earliest_time" || name === "visit_time") return formatWhen(value);
  if (name === "visiting_charge") return `${formatRupees(value)} visit`;
  if (name === "interested") return value.toLowerCase() === "yes" ? "Interested" : "Not interested";
  if (/^answer_\d+$/.test(name)) return `${factLabel(name)} answered`;
  if (name in FACT_LABELS) return `${FACT_LABELS[name]}: ${value}`;
  return value;
}

function Timer({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return <>{formatClock((now - since) / 1000)}</>;
}
