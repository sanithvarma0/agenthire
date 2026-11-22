// Candidates screen (docs/LLD.md, section 17): the public profiles found by web crawling for
// this role (on screen "web crawling"; in code, the model's web search tool reading public
// pages). No contact details are taken, so nobody here is ever contacted: a screening call
// for one of them rings the builder's own number instead (the demo fallback).

import { useState } from "react";
import { Check, ExternalLink, FileText, Globe, PhoneCall, PhoneForwarded, Search, ShieldCheck } from "lucide-react";
import { api, type Job, type Person } from "../api";
import { useJob } from "../store";
import { initials, JobLayout, JobSummary, StepRail } from "../components/Frame";

const MOST = 3; // calling.max_calls_per_job

export function Candidates({ job }: { job: Job }) {
  const crawling = job.step === "sourcing";
  const found = job.people.filter((p) => p.source === "web");
  const note = job.search?.sourced;
  const [marked, setMarked] = useState<string[]>([]);
  const [hint, setHint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toggle = (id: string) => {
    setHint(null);
    if (marked.includes(id)) return setMarked(marked.filter((m) => m !== id));
    if (marked.length >= MOST) return setHint(`Up to ${MOST} screening calls per role. Untick one to swap.`);
    setMarked([...marked, id]);
  };

  const screen = async () => {
    if (marked.length === 0) return setHint("Tick at least one candidate to screen.");
    setBusy(true);
    try {
      useJob.setState({ job: await api.approve(job.id, found.filter((p) => marked.includes(p.id)).map((p) => p.id)) });
    } catch (err) {
      setHint(`Couldn't start the calls: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const stage = (
    <>
      <div>
        <p className="eyebrow accent" style={{ marginBottom: 8 }}>Candidates</p>
        <h1 className="title lg">{job.posting?.title ?? "The role"}</h1>
      </div>

      <section className="panel stack">
        <div className="panel-head" style={{ marginBottom: 0 }}>
          <p className="eyebrow row" style={{ gap: 6 }}><Globe size={13} />Found by web crawling{crawling ? "" : ` · ${found.length}`}</p>
          <span className="chip" title="Phone numbers and emails are never taken"><ShieldCheck size={13} />No contact details</span>
        </div>
        {crawling ? (
          <div className="stack">
            <div className="locating"><Search size={16} className="accent" />Crawling the web for public profiles that fit the role…</div>
            <div className="skeleton" aria-hidden="true"><span /><span /><span style={{ width: "70%" }} /></div>
          </div>
        ) : found.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>{note?.error ?? "No public profiles found for this role."}</p>
        ) : (
          <>
            <p className="faint small" style={{ margin: 0 }}>
              Public profiles that fit the role{note?.seconds ? `, crawled in ${Math.round(note.seconds)} s` : ""}. Tap up
              to {MOST} to screen by phone.
            </p>
            <ul className="clist grid">
              {found.map((p) => <ProfileCard key={p.id} person={p} marked={marked.includes(p.id)} onToggle={() => toggle(p.id)} />)}
            </ul>
          </>
        )}
      </section>

      {found.length > 0 && (
        <>
          <div className="notice warn"><PhoneForwarded size={17} />
            We never take their numbers, so a screening call for anyone here rings your phone instead, and you answer as them.
            The result is labelled as answered by you.
          </div>
          {hint && <p className="error" role="alert">{hint}</p>}
          <div className="controls sticky-actions">
            <button className="btn" onClick={screen} aria-busy={busy}>
              <PhoneCall size={17} />{busy ? "Starting…" : marked.length === 0 ? "Tick candidates to screen" : `Screen ${marked.length === 1 ? "this 1" : `these ${marked.length}`}`}
            </button>
          </div>
        </>
      )}
    </>
  );

  const rail = (
    <>
      <StepRail job={job} />
      <JobSummary job={job} />
      {job.posting && (
        <section className="panel tight">
          <details className="more">
            <summary><FileText size={14} />The approved posting · {job.posting.questions.length} questions</summary>
            <p className="jd small" style={{ marginTop: 10 }}>{job.posting.job_description}</p>
            <ol className="qlist plain small" style={{ marginTop: 10 }}>
              {job.posting.questions.map((q, i) => <li key={i}><span className="rank">{i + 1}</span>{q.question}</li>)}
            </ol>
          </details>
        </section>
      )}
    </>
  );
  return <JobLayout stage={stage} rail={rail} />;
}

function ProfileCard({ person, marked, onToggle }: { person: Person; marked: boolean; onToggle: () => void }) {
  const where = [person.company, person.location ?? person.address].filter(Boolean).join(" · ");
  return (
    // The whole card ticks it (the checkbox on the right is the keyboard and screen-reader way).
    <li className={`ccard ${marked ? "marked" : ""}`} onClick={onToggle}>
      <span className="avatar-sq sm" aria-hidden="true">{marked ? <Check size={18} strokeWidth={3} /> : initials(person.name)}</span>
      <button className="check ctick" aria-pressed={marked} aria-label={`Screen ${person.name}`}
        onClick={(e) => { e.stopPropagation(); onToggle(); }}>
        {marked && <Check size={16} strokeWidth={3} />}
      </button>
      <div className="who">
        <strong>{person.name}</strong>
        {person.headline && <span className="headline">{person.headline}</span>}
        {where && <span className="faint small">{where}</span>}
        {person.experience && person.experience !== person.headline && <span className="exp small">{person.experience}</span>}
        {person.profile_url && (
          <a className="plink" href={person.profile_url} target="_blank" rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}>
            <ExternalLink size={13} />{hostOf(person.profile_url)}
          </a>
        )}
      </div>
    </li>
  );
}

function hostOf(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\.|^in\./, "") + (u.pathname.length > 1 ? u.pathname.replace(/\/$/, "") : "");
  } catch {
    return url;
  }
}
