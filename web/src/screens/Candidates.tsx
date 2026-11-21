// Candidates screen (docs/LLD.md, section 17): the public profiles found by web crawling for
// this role (on screen "web crawling"; in code, the model's web search tool reading public
// pages). No contact details are taken, so nobody here is ever contacted: a screening call
// for one of them rings the builder's own number instead (the demo fallback).

import { ExternalLink, FileText, Globe, PhoneForwarded, Search, ShieldCheck } from "lucide-react";
import type { Job, Person } from "../api";
import { initials, JobLayout, JobSummary, StepRail } from "../components/Frame";

export function Candidates({ job }: { job: Job }) {
  const crawling = job.step === "sourcing";
  const found = job.people.filter((p) => p.source === "web");
  const note = job.search?.sourced;

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
              Public profiles that fit the role{note?.seconds ? `, crawled in ${Math.round(note.seconds)} s` : ""}. Check each
              profile yourself before reaching out.
            </p>
            <ul className="clist grid">{found.map((p) => <ProfileCard key={p.id} person={p} />)}</ul>
          </>
        )}
      </section>

      {found.length > 0 && (
        <div className="notice warn"><PhoneForwarded size={17} />
          We never take their numbers, so a screening call for anyone here rings your phone instead, and you answer as them.
          The result is labelled as answered by you.
        </div>
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

function ProfileCard({ person }: { person: Person }) {
  const where = [person.company, person.location ?? person.address].filter(Boolean).join(" · ");
  return (
    <li className="ccard">
      <span className="avatar-sq sm" aria-hidden="true">{initials(person.name)}</span>
      <div className="who">
        <strong>{person.name}</strong>
        {person.headline && <span className="headline">{person.headline}</span>}
        {where && <span className="faint small">{where}</span>}
        {person.experience && person.experience !== person.headline && <span className="exp small">{person.experience}</span>}
        {person.profile_url && (
          <a className="plink" href={person.profile_url} target="_blank" rel="noopener noreferrer">
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
