// The parts every job screen shares: the top bar, the step rail and the job summary. Home and
// company jobs share the layout; the rail and the summary follow the job's side.

import type { ReactNode } from "react";
import {
  Briefcase, CalendarCheck, Check, FileText, FlaskConical, History, Languages, ListChecks, MapPin, Mic,
  PhoneCall, Scale, Sparkles, Users, Wrench,
} from "lucide-react";
import { roleOf, type Job } from "../api";
import { useJob } from "../store";

const LANGUAGE_NAMES: Record<string, string> = { te: "తెలుగు", hi: "हिंदी", en: "English" };

export type Nav = "choose" | "gig" | "hire" | "history" | "job";

export function TopBar({ onHome, onGig, onHire, onHistory, at }: {
  onHome: () => void; onGig: () => void; onHire: () => void; onHistory: () => void; at: Nav;
}) {
  const job = useJob((s) => s.job);
  const company = job?.side === "company";
  return (
    <header className="topbar">
      <button className="brand" onClick={onHome} aria-label="AgentHire home">
        <span className="brand-mark" aria-hidden="true"><Sparkles size={16} strokeWidth={2.4} /></span>
        AgentHire
      </button>
      <div className="chips">
        <button className={`navlink ${at === "gig" || (at === "job" && job && !company) ? "on" : ""}`} onClick={onGig}
          aria-current={at === "gig" ? "page" : undefined} aria-label="Gig worker">
          <Wrench size={15} /><span className="hide-xs">Gig</span>
        </button>
        <button className={`navlink ${at === "hire" || (at === "job" && company) ? "on" : ""}`} onClick={onHire}
          aria-current={at === "hire" ? "page" : undefined} aria-label="IT hire">
          <Briefcase size={15} /><span className="hide-xs">IT</span>
        </button>
        <button className={`navlink ${at === "history" ? "on" : ""}`} onClick={onHistory}
          aria-current={at === "history" ? "page" : undefined}>
          <History size={15} /><span className="hide-xs">History</span>
        </button>
        {job?.start && !company && (
          <>
            <span className="chip hide-sm"><Languages size={13} />{LANGUAGE_NAMES[job.start.language] ?? job.start.language}</span>
            {job.start.area && <span className="chip hide-sm"><MapPin size={13} />{shortArea(job.start.area)}</span>}
          </>
        )}
        {company && job?.start?.company && <span className="chip hide-sm"><Briefcase size={13} />{job.start.company}</span>}
        {(job?.test_mode ?? true) && (
          <span className="chip warn" title="Calls and messages go to the builder's phone, not to the people found">
            <FlaskConical size={13} /><span className="hide-xs">Test mode</span><span className="show-xs">Test</span>
          </span>
        )}
      </div>
    </header>
  );
}

const HOME_STEPS = [
  { label: "Tell us what's wrong", icon: Mic, steps: ["briefing"] },
  { label: "Find people nearby", icon: MapPin, steps: ["finding", "awaiting_approval"] },
  { label: "Call around", icon: PhoneCall, steps: ["calling"] },
  { label: "Compare", icon: Scale, steps: ["reporting", "awaiting_pick"] },
  { label: "Book", icon: CalendarCheck, steps: ["confirming", "done"] },
];

const COMPANY_STEPS = [
  { label: "Describe the role", icon: Mic, steps: ["briefing"] },
  { label: "Job description", icon: FileText, steps: ["writing", "awaiting_posting"] },
  { label: "Candidates", icon: Users, steps: ["sourcing", "awaiting_approval"] },
  { label: "Screening calls", icon: PhoneCall, steps: ["calling"] },
  { label: "Shortlist", icon: ListChecks, steps: ["scoring", "done"] },
];

export function StepRail({ job }: { job: Job }) {
  const steps = job.side === "company" ? COMPANY_STEPS : HOME_STEPS;
  const at = steps.findIndex((s) => s.steps.includes(job.step));
  const finished = job.step === "done";
  return (
    <section className="panel tight" aria-label="Progress">
      <p className="eyebrow" style={{ marginBottom: 8 }}>{job.side === "company" ? "Your hire" : "Your request"}</p>
      <ol className="steps">
        {steps.map((step, i) => {
          const state = finished || i < at ? "done" : i === at ? "now" : "";
          const Icon = state === "done" ? Check : step.icon;
          return (
            <li key={step.label} className={state} aria-current={state === "now" ? "step" : undefined}>
              <span className="ic"><Icon size={15} strokeWidth={2.2} /></span>
              <span>{step.label}{state === "now" && <span className="note">{noteFor(job)}</span>}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function noteFor(job: Job): string {
  if (job.side === "company") {
    return ({
      briefing: job.start?.request ? "Reading the role…" : "Talking with you now",
      writing: "Writing it for you…",
      awaiting_posting: "Check it and approve",
      sourcing: "Crawling the web…",
      awaiting_approval: "Pick who to screen",
      calling: "Calling candidates",
      scoring: "Scoring the answers…",
      done: "Ready",
    } as Record<string, string>)[job.step] ?? "";
  }
  const called = job.conversations.filter((c) => c.kind === "home_call").length;
  const approved = job.people.filter((p) => p.approved).length;
  return ({
    briefing: job.start?.request ? "Reading your request…" : "Talking with you now",
    finding: "Searching the map…",
    awaiting_approval: `${job.people.length} found · pick who to call`,
    calling: `Call ${Math.max(called, 1)} of ${approved || 2}`,
    reporting: "Comparing the answers…",
    awaiting_pick: "Your choice",
    confirming: "Confirming the visit",
    done: "Scheduled",
  } as Record<string, string>)[job.step] ?? "";
}

export function JobSummary({ job, children }: { job: Job; children?: ReactNode }) {
  const role = roleOf(job);
  if (job.side === "company") {
    return (
      <section className="panel tight">
        <p className="eyebrow" style={{ marginBottom: 10 }}>The role</p>
        <dl className="kv">
          {job.start?.company && (<><dt>Company</dt><dd>{job.start.company}</dd></>)}
          {role?.role && (<><dt>Role</dt><dd>{role.role}</dd></>)}
          {role?.must_haves.length ? (<><dt>Must have</dt><dd>{role.must_haves.join(", ")}</dd></>) : null}
          {role?.experience && (<><dt>Experience</dt><dd>{role.experience}</dd></>)}
          {role?.location && (<><dt>Where</dt><dd>{role.location}</dd></>)}
          {!role && job.start?.request && (<><dt>Asked</dt><dd>{job.start.request}</dd></>)}
        </dl>
        {children}
      </section>
    );
  }
  const what = job.brief?.work ?? job.start?.request;
  return (
    <section className="panel tight">
      <p className="eyebrow" style={{ marginBottom: 10 }}>The job</p>
      <dl className="kv">
        {what && (<><dt>Problem</dt><dd>{what}</dd></>)}
        {job.brief?.service && (<><dt>Who</dt><dd style={{ textTransform: "capitalize" }}>{job.brief.service}</dd></>)}
        {job.start?.area && (<><dt>Where</dt><dd>{job.start.area}</dd></>)}
      </dl>
      {children}
    </section>
  );
}

export function JobLayout({ stage, rail }: { stage: ReactNode; rail: ReactNode }) {
  return (
    <div className="job fade-in">
      <main className="stage">{stage}</main>
      <aside className="rail">{rail}</aside>
    </div>
  );
}

function shortArea(area: string): string {
  return area.split(",").slice(0, 2).join(",").trim();
}

export function initials(name: string): string {
  const words = name.replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return (words.slice(0, 2).map((w) => w[0]).join("") || "?").toUpperCase();
}
