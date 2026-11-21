// History screen (docs/LLD.md, section 15): every request made from this app, newest first,
// with how far it got: booked (who, when, the charge), stopped (and why), or the step it is
// waiting at. A row opens the job at its current step.

import { useEffect, useState } from "react";
import { AlertTriangle, Briefcase, CalendarCheck, ChevronRight, Clock, Inbox, PhoneCall, Plus } from "lucide-react";
import { api, roleOf, type JobSummary } from "../api";
import { formatRupees, formatWhen } from "../format";
import { stepLabel } from "./Start";

export function History({ onOpen, onNew }: { onOpen: (jobId: string) => void; onNew: () => void }) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.history().then(setJobs).catch((err: Error) => setError(err.message));
  }, []);

  const booked = jobs?.filter((j) => j.booked).length ?? 0;
  const called = jobs?.reduce((sum, j) => sum + j.called, 0) ?? 0;

  return (
    <div className="history fade-in">
      <div className="history-head">
        <div>
          <p className="eyebrow accent" style={{ marginBottom: 8 }}>History</p>
          <h1 className="title lg">Your requests</h1>
        </div>
        <button className="btn" onClick={onNew}><Plus size={17} />New request</button>
      </div>

      {jobs && jobs.length > 0 && (
        <div className="numbers history-stats">
          <div className="num"><span><Inbox size={12} />Requests</span><strong className="plain">{jobs.length}</strong></div>
          <div className="num"><span><PhoneCall size={12} />Calls</span><strong className="plain">{called}</strong></div>
          <div className="num"><span><CalendarCheck size={12} />Booked</span><strong>{booked}</strong></div>
        </div>
      )}

      {error && <div className="notice bad" role="alert"><AlertTriangle size={17} />Couldn't load the history: {error}</div>}
      {!jobs && !error && <div className="locating"><span className="you-dot" aria-hidden="true" />Loading…</div>}
      {jobs && jobs.length === 0 && (
        <section className="panel stack" style={{ justifyItems: "start" }}>
          <p className="muted" style={{ margin: 0 }}>Nothing here yet. Your requests appear here once you start one.</p>
          <button className="btn ghost" onClick={onNew}><Plus size={16} />Start a request</button>
        </section>
      )}

      {jobs && jobs.length > 0 && (
        <ul className="hlist">
          {jobs.map((j) => <HistoryRow key={j.id} job={j} onOpen={() => onOpen(j.id)} />)}
        </ul>
      )}
    </div>
  );
}

function HistoryRow({ job, onOpen }: { job: JobSummary; onOpen: () => void }) {
  const role = roleOf(job);
  const what = role ? `${role.role} at ${role.company}` : job.brief?.work ?? job.request
    ?? (job.side === "company" ? `Role at ${job.company ?? "a company"}, not finished` : "Voice request, not finished");
  const failed = job.status === "failed";
  return (
    <li>
      <button className="hrow" onClick={onOpen}>
        <span className="hdate">
          <strong>{dayOf(job.created_at)}</strong>
          <span>{timeOf(job.created_at)}</span>
        </span>
        <span className="hwhat">
          <span className="hproblem">{what}</span>
          <span className="meta">
            {job.side === "company" && <span className="accent"><Briefcase size={12} />Hiring</span>}
            {role?.location && <span>{role.location}</span>}
            {!role && job.brief?.service && <span style={{ textTransform: "capitalize" }}>{job.brief.service}</span>}
            {job.area && <span>{job.area.split(",")[0]}</span>}
            {job.found > 0 && <span>{job.found} found</span>}
            {job.called > 0 && <span>{job.called} called{job.available ? `, ${job.available} can come` : ""}</span>}
          </span>
        </span>
        <span className="hend">
          {job.booked ? (
            <>
              <span className="chip good"><CalendarCheck size={13} />Booked</span>
              <span className="hbooked">
                {job.booked.name}
                {job.booked.visit_time && <> · {formatWhen(job.booked.visit_time)}</>}
                {job.booked.visiting_charge && <> · {formatRupees(job.booked.visiting_charge)}</>}
              </span>
            </>
          ) : failed ? (
            <>
              <span className="chip bad"><AlertTriangle size={13} />Didn't finish</span>
              {job.error && <span className="hbooked faint">{job.error}</span>}
            </>
          ) : (
            <span className="chip warn"><Clock size={13} />{job.side === "company" ? companyStepLabel(job.step) : stepLabel(job.step)}</span>
          )}
        </span>
        <ChevronRight size={18} className="faint hchev" />
      </button>
    </li>
  );
}

function companyStepLabel(step: string): string {
  return ({
    briefing: "Started", writing: "Writing", awaiting_posting: "Check the posting", sourcing: "Finding candidates",
    awaiting_approval: "Applications open", calling: "Screening", scoring: "Scoring", done: "Shortlist ready",
  } as Record<string, string>)[step] ?? step;
}

function dayOf(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const days = Math.round((new Date(today.toDateString()).getTime() - new Date(date.toDateString()).getTime()) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}
