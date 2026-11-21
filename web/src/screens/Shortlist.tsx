// Shortlist screen (docs/LLD.md, section 17): the candidates ranked by their screening calls.
// Every score shows the candidate's own words it rests on (checked against the transcript);
// questions not reached say so. Scores judge content only, never accent or fluency.

import { FlaskConical, ListChecks, Quote, RotateCcw, Trophy } from "lucide-react";
import type { Job, ShortlistEntry } from "../api";
import { initials, JobLayout, JobSummary, StepRail } from "../components/Frame";
import { OUTCOME_LABELS } from "../format";
import { useJob } from "../store";
import { Transcript } from "./Brief";

const DETAIL_LABELS: Record<string, string> = {
  expected_salary: "Expected", current_salary: "Current", notice_period: "Notice", location: "Location",
};

export function Shortlist({ job, onRestart }: { job: Job; onRestart: () => void }) {
  const entries = job.report?.shortlist ?? [];
  const ranked = entries.filter((e) => e.score !== null);
  const rest = entries.filter((e) => e.score === null);

  const stage = (
    <>
      <div>
        <p className="eyebrow accent" style={{ marginBottom: 8 }}>Shortlist · {entries.length} screened</p>
        <h1 className="title lg">{job.posting?.title ?? "The role"}</h1>
        <p className="muted" style={{ margin: "8px 0 0" }}>
          {ranked.length ? "Ranked by their answers. Every score quotes what the candidate said on the call." : "Nobody answered the screening questions this time."}
        </p>
      </div>
      {ranked.map((e) => <Candidate key={e.conversation_id} entry={e} job={job} />)}
      {rest.length > 0 && (
        <section className="panel tight stack">
          <p className="eyebrow">Not shortlisted</p>
          {rest.map((e) => (
            <div key={e.conversation_id} className="qitem">
              <span className="avatar-sq sm">{initials(e.name)}</span>
              <div className="who"><strong>{e.name}</strong><span className="faint small">{e.headline}</span></div>
              <span className="chip bad">{OUTCOME_LABELS[e.outcome] ?? e.outcome}</span>
            </div>
          ))}
        </section>
      )}
      <button className="btn ghost" onClick={onRestart} style={{ justifySelf: "start" }}><RotateCcw size={16} />Start something else</button>
    </>
  );

  const rail = (
    <>
      <StepRail job={job} />
      <JobSummary job={job} />
      <section className="panel tight">
        <p className="eyebrow row" style={{ gap: 6, marginBottom: 8 }}><ListChecks size={13} />How it's scored</p>
        <p className="faint small" style={{ margin: 0 }}>
          Each answer is scored from 1 to 5 against the guide you approved. A score is shown only if the candidate's own words
          behind it are in the transcript. Content only: never accent, fluency or grammar.
        </p>
      </section>
    </>
  );
  return <JobLayout stage={stage} rail={rail} />;
}

function Candidate({ entry, job }: { entry: ShortlistEntry; job: Job }) {
  const events = useJob((s) => s.events);
  const lines = events.filter((e) => e.conversation_id === entry.conversation_id && (e.type === "agent_said" || e.type === "person_said"));
  const first = entry.rank === 1;
  return (
    <section className={`offer fade-in ${first ? "best" : ""}`}>
      {first && <span className="ribbon"><Trophy size={13} />Top of the shortlist</span>}
      <div className="call-head">
        <span className="avatar-sq">{entry.rank ?? initials(entry.name)}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p className="title md">{entry.name}</p>
          {entry.headline && <span className="faint small">{entry.headline}</span>}
        </div>
        <div className="score-big" aria-label={`Score ${entry.score} out of 5`}>
          <strong>{entry.score?.toFixed(1)}</strong><span>/ 5</span>
        </div>
      </div>
      {entry.routed && (
        <span className="routed"><FlaskConical size={13} />Answered by you on the demo call, not by {entry.name}</span>
      )}
      {entry.summary && <p className="muted" style={{ margin: 0 }}>{entry.summary}</p>}

      <ol className="answers">
        {entry.answers.map((a) => (
          <li key={a.question}>
            <div className="ahead">
              <span className="qnum">Q{a.question}</span>
              <span className="qtext">{a.text}</span>
              {a.score ? <span className={`pill s${a.score}`}>{a.score}/5</span> : <span className="pill none">{a.answer ? "Not scored" : "Not asked"}</span>}
            </div>
            {a.quote && <p className="quote"><Quote size={12} /> {a.quote}</p>}
            {a.reason && <p className="faint small" style={{ margin: 0 }}>{a.reason}</p>}
          </li>
        ))}
      </ol>

      {Object.keys(entry.details).length > 0 && (
        <div className="facts">
          {Object.entries(entry.details).map(([k, d]) => (
            <span key={k} className="fact got" title={`"${d.said_as}"`}>{DETAIL_LABELS[k] ?? k}: {d.value}</span>
          ))}
        </div>
      )}
      <p className="faint small" style={{ margin: 0 }}>{entry.scored} of {job.posting?.questions.length ?? entry.answers.length} questions scored</p>
      {lines.length > 0 && (
        <details className="more"><summary>Show the call</summary><Transcript lines={lines} them={entry.name} /></details>
      )}
    </section>
  );
}
