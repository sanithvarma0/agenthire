// One page for a job that follows its step (docs/LLD.md, section 15). Each step has its own
// screen; all of them share the two-column layout (stage and rail) from components/Frame.

import { useEffect } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { JobLayout, JobSummary, StepRail } from "../components/Frame";
import { useJob } from "../store";
import { Confirming, Scheduled } from "./Booking";
import { Brief } from "./Brief";
import { Calls } from "./Calls";
import { Candidates } from "./Candidates";
import { PostingEditor, Writing } from "./Posting";
import { Finding, Providers } from "./Providers";
import { Report } from "./Report";
import { Shortlist } from "./Shortlist";
import { stepLabel } from "./Start";

export function JobScreen({ jobId, onRestart }: { jobId: string; onRestart: () => void }) {
  const { job, error, open, close, refresh } = useJob();

  useEffect(() => {
    void open(jobId);
    return close;
  }, [jobId, open, close]);

  if (error) return <div className="notice bad" role="alert"><AlertTriangle size={17} />Couldn't load this job: {error}</div>;
  if (!job) return <div className="locating"><span className="you-dot" aria-hidden="true" />Loading…</div>;

  if (job.status === "failed") {
    const stage = (
      <section className="panel stack">
        <div className="notice bad"><AlertTriangle size={17} />{job.error ?? "Something went wrong."}</div>
        <button className="btn ghost" onClick={onRestart} style={{ justifySelf: "start" }}><RotateCcw size={16} />Start again</button>
      </section>
    );
    return <JobLayout stage={stage} rail={<><StepRail job={job} /><JobSummary job={job} /></>} />;
  }
  if (job.step === "briefing" && !job.start?.request) return <Brief job={job} />;
  if (job.side === "company") {
    if (job.step === "briefing" || job.step === "writing") return <Writing job={job} />;
    if (job.step === "awaiting_posting") return <PostingEditor job={job} />;
    if (job.step === "sourcing" || job.step === "awaiting_approval") return <Candidates job={job} />;
    if (job.step === "calling" || job.step === "scoring") return <Calls job={job} />;
    if (job.step === "done") return <Shortlist job={job} onRestart={onRestart} />;
  }
  if (job.step === "briefing" || job.step === "finding") return <Finding job={job} />;
  if (job.step === "awaiting_approval") return <Providers job={job} onApproved={() => void refresh()} />;
  if (job.step === "calling" || job.step === "reporting") return <Calls job={job} />;
  if (job.step === "awaiting_pick") return <Report job={job} onRestart={onRestart} />;
  if (job.step === "confirming") return <Confirming job={job} />;
  if (job.step === "done") return <Scheduled job={job} onRestart={onRestart} />;
  return <JobLayout stage={<h1 className="title lg">{stepLabel(job.step)}</h1>} rail={<StepRail job={job} />} />;
}
