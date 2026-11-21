// Report screen (docs/LLD.md, section 15): one offer per provider called, the recommended one
// first with one line of reasoning, and the provider's own words as proof. The user picks;
// the agent never books on its own.

import { useState } from "react";
import { CalendarCheck, Clock, FlaskConical, IndianRupee, MapPin, RotateCcw, Sparkles, Star, XCircle } from "lucide-react";
import { api, type Conversation, type Job, type JobEvent, type Person } from "../api";
import { initials, JobLayout, JobSummary, StepRail } from "../components/Frame";
import { formatRupees, formatWhen, OUTCOME_LABELS } from "../format";
import { useJob } from "../store";
import { Transcript } from "./Brief";
import { factsOf, uniqueQuotes } from "./Calls";

export function Report({ job, onRestart }: { job: Job; onRestart: () => void }) {
  const events = useJob((s) => s.events);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const report = job.report;
  const called = job.conversations.filter((c) => c.result && c.kind === "home_call");
  const unavailable = new Set(report?.unavailable ?? []);
  // A recommended provider who then could not confirm is no longer the recommendation.
  const recommended = report?.recommended_person_id && !unavailable.has(report.recommended_person_id)
    ? report.recommended_person_id : null;
  // The recommended provider first, then the rest in the order they were called.
  const order = [...called].sort((a, b) => Number(b.person_id === recommended) - Number(a.person_id === recommended));
  const person = (id: string | null) => job.people.find((p) => p.id === id);
  const best = person(recommended);

  const book = async (personId: string) => {
    setBusy(personId);
    setError(null);
    try {
      await api.pick(job.id, personId);
      await useJob.getState().refresh();
    } catch (err) {
      setError(`Couldn't book: ${(err as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const stage = (
    <>
      {report?.notice && <div className="notice warn" role="status"><XCircle size={17} />{report.notice} Pick someone else below.</div>}
      <div>
        <p className="eyebrow accent" style={{ marginBottom: 8 }}>{called.length} {called.length === 1 ? "call" : "calls"} made · here's what they said</p>
        <h1 className="title lg">{best ? <>{best.name} <span className="accent">looks best</span></> : "Nobody could come this time"}</h1>
        <p className="muted" style={{ margin: "8px 0 0" }}>{report?.reasoning ?? "None of the providers called can take the job."}</p>
      </div>
      {order.map((conv) => {
        const p = person(conv.person_id);
        if (!p) return null;
        return (
          <Offer
            key={conv.id} person={p} conversation={conv} recommended={conv.person_id === recommended}
            unavailable={unavailable.has(p.id)}
            events={events.filter((e) => e.conversation_id === conv.id)}
            busy={busy === p.id} onBook={() => book(p.id)}
          />
        );
      })}
      {error && <p className="error" role="alert">{error}</p>}
      {!best && <button className="btn ghost" onClick={onRestart}><RotateCcw size={16} />Start again</button>}
    </>
  );
  return <JobLayout stage={stage} rail={<><StepRail job={job} /><JobSummary job={job} /></>} />;
}

function Offer({ person, conversation, recommended, unavailable, events, busy, onBook }: {
  person: Person; conversation: Conversation; recommended: boolean; unavailable: boolean; events: JobEvent[];
  busy: boolean; onBook: () => void;
}) {
  const result = conversation.result!;
  const facts = factsOf(result);
  const can = result.outcome === "available" && !unavailable;
  const lines = events.filter((e) => e.type === "agent_said" || e.type === "person_said");
  const quotes = uniqueQuotes(result.facts.filter((f) => f.verified !== false));
  return (
    <section className={`offer fade-in ${recommended ? "best" : ""}`}>
      {recommended && <span className="ribbon"><Sparkles size={13} />Recommended</span>}
      <div className="call-head">
        <span className="avatar-sq">{initials(person.name)}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p className="title md">{person.name}</p>
          <span className="meta faint small">
            {person.rating != null && <span><Star size={12} fill="currentColor" />{person.rating.toFixed(1)} ({person.review_count ?? 0})</span>}
            {person.distance_km != null && <span><MapPin size={12} />{person.distance_km.toFixed(1)} km</span>}
          </span>
        </div>
        <span className={`chip ${can ? "good" : "bad"}`}>{unavailable ? "Couldn't confirm" : OUTCOME_LABELS[result.outcome] ?? result.outcome}</span>
      </div>
      {can && (
        <div className="numbers">
          <div className="num"><span><Clock size={12} />When</span><strong>{facts.earliest_time ? formatWhen(facts.earliest_time) : "Not said"}</strong></div>
          <div className="num"><span><IndianRupee size={12} />Visit</span><strong>{facts.visiting_charge ? formatRupees(facts.visiting_charge) : "Not said"}</strong></div>
          <div className="num"><span><Star size={12} />Rating</span><strong className="plain">{person.rating != null ? person.rating.toFixed(1) : "None"}</strong></div>
        </div>
      )}
      {quotes.map((q) => <p key={q} className="quote">“{q}”</p>)}
      {result.notes && <p className="faint small" style={{ margin: 0 }}>{result.notes}</p>}
      {conversation.routed_to && <span className="routed"><FlaskConical size={13} />Test mode: answered by you, not by {person.name}</span>}
      {lines.length > 0 && (
        <details className="more"><summary>Show the conversation</summary><Transcript lines={lines} them={person.name} /></details>
      )}
      {can && (
        <button className={`btn ${recommended ? "lg" : "ghost"} block`} onClick={onBook} aria-busy={busy}>
          <CalendarCheck size={17} />{busy ? "Booking…" : `Book ${person.name}`}
        </button>
      )}
    </section>
  );
}
