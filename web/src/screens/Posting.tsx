// Posting screens (docs/LLD.md, section 17). While the role is read, a short wait; then HR
// checks the job description and the screening questions, each with its scoring guide, edits
// anything, and approves. Nothing is sourced, sent or called before that.

import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, Plus, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { api, type Job, type PostingEdit, type ScreeningQuestion } from "../api";
import { JobLayout, JobSummary, StepRail } from "../components/Frame";
import { useJob } from "../store";

const MAX_QUESTIONS = 5;

export function Writing({ job }: { job: Job }) {
  const stage = (
    <section className="panel writing">
      <div className="writing-mark" aria-hidden="true"><Sparkles size={26} /></div>
      <h1 className="title lg">Writing the job description</h1>
      <p className="muted" style={{ margin: 0 }}>
        The job description, five screening questions in order of priority, and a guide to scoring each answer.
        You'll check all of it before anything goes out.
      </p>
      <div className="skeleton" aria-hidden="true"><span /><span /><span style={{ width: "62%" }} /></div>
    </section>
  );
  return <JobLayout stage={stage} rail={<><StepRail job={job} /><JobSummary job={job} /></>} />;
}

export function PostingEditor({ job }: { job: Job }) {
  const [draft, setDraft] = useState<PostingEdit>(() => fromJob(job));
  const [busy, setBusy] = useState<"save" | "approve" | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setDraft(fromJob(job)), [job.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const setQuestion = (i: number, q: Partial<ScreeningQuestion>) => {
    setSaved(false);
    setDraft({ ...draft, questions: draft.questions.map((x, j) => (j === i ? { ...x, ...q } : x)) });
  };
  const removeQuestion = (i: number) => {
    setSaved(false);
    setDraft({ ...draft, questions: draft.questions.filter((_, j) => j !== i) });
  };
  const addQuestion = () => {
    setSaved(false);
    setDraft({ ...draft, questions: [...draft.questions, { question: "", strong: "", average: "", weak: "" }] });
  };

  const problem = (): string | null => {
    if (draft.title.trim().length < 2) return "Add a title.";
    if (draft.job_description.trim().length < 20) return "The job description is too short.";
    if (draft.questions.length === 0) return "Keep at least one question.";
    if (draft.questions.some((q) => q.question.trim().length < 3)) return "One of the questions is empty.";
    return null;
  };

  const send = async (what: "save" | "approve") => {
    const wrong = problem();
    if (wrong) return setError(wrong);
    setError(null);
    setBusy(what);
    try {
      const clean = { ...draft, questions: draft.questions.map((q) => ({ ...q, question: q.question.trim() })) };
      const updated = what === "save" ? await api.savePosting(job.id, clean) : await api.approvePosting(job.id, clean);
      if (what === "save") setSaved(true);
      useJob.setState({ job: updated });
    } catch (err) {
      setError(`Couldn't ${what === "save" ? "save" : "approve"}: ${(err as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const stage = (
    <>
      <div>
        <p className="eyebrow accent" style={{ marginBottom: 8 }}>Check before it goes out</p>
        <h1 className="title lg">The job description and screening questions</h1>
      </div>

      <section className="panel stack">
        <label className="field"><span>Title</span>
          <input className="title-input" value={draft.title} onChange={(e) => { setSaved(false); setDraft({ ...draft, title: e.target.value }); }} />
        </label>
        <label className="field"><span>Job description</span>
          <textarea value={draft.job_description} rows={12}
            onChange={(e) => { setSaved(false); setDraft({ ...draft, job_description: e.target.value }); }} />
        </label>
      </section>

      <section className="panel stack">
        <div className="panel-head" style={{ marginBottom: 0 }}>
          <p className="eyebrow">Screening questions · asked in this order</p>
          <span className="faint small">{draft.questions.length} of {MAX_QUESTIONS}</span>
        </div>
        <p className="faint small" style={{ margin: 0 }}>
          The call lasts about 3 minutes, so the first questions matter most; any not reached show as "not asked".
          Salary, notice period, location and interest are asked separately.
        </p>
        <ol className="qlist">
          {draft.questions.map((q, i) => (
            <li key={i} className="qcard">
              <div className="qrow">
                <span className="rank" aria-hidden="true">{i + 1}</span>
                <textarea value={q.question} rows={2} aria-label={`Question ${i + 1}`}
                  onChange={(e) => setQuestion(i, { question: e.target.value })} />
                <button className="icon-btn" onClick={() => removeQuestion(i)} aria-label={`Remove question ${i + 1}`}
                  disabled={draft.questions.length === 1}><Trash2 size={16} /></button>
              </div>
              <details className="guide">
                <summary><ChevronDown size={14} />Scoring guide</summary>
                <div className="guide-grid">
                  <label className="field good"><span>Strong answer</span>
                    <textarea rows={2} value={q.strong} onChange={(e) => setQuestion(i, { strong: e.target.value })} /></label>
                  <label className="field mid"><span>Average answer</span>
                    <textarea rows={2} value={q.average} onChange={(e) => setQuestion(i, { average: e.target.value })} /></label>
                  <label className="field low"><span>Weak answer</span>
                    <textarea rows={2} value={q.weak} onChange={(e) => setQuestion(i, { weak: e.target.value })} /></label>
                </div>
              </details>
            </li>
          ))}
        </ol>
        {draft.questions.length < MAX_QUESTIONS && (
          <button className="btn ghost sm" onClick={addQuestion} style={{ justifySelf: "start" }}><Plus size={15} />Add a question</button>
        )}
      </section>

      {error && <p className="error" role="alert">{error}</p>}
      <div className="controls sticky-actions">
        <button className="btn ghost" onClick={() => send("save")} aria-busy={busy === "save"}>
          {saved ? <><CheckCircle2 size={16} />Saved</> : busy === "save" ? "Saving…" : "Save changes"}
        </button>
        <button className="btn" onClick={() => send("approve")} aria-busy={busy === "approve"}>
          <ShieldCheck size={17} />{busy === "approve" ? "Approving…" : "Approve"}
        </button>
      </div>
    </>
  );

  const rail = (
    <>
      <StepRail job={job} />
      <JobSummary job={job} />
      <section className="panel tight">
        <p className="eyebrow" style={{ marginBottom: 8 }}>How answers are scored</p>
        <p className="faint small" style={{ margin: 0 }}>
          Each answer is scored from 1 to 5 against its guide, and every score quotes what the candidate said.
          Content only: never accent, fluency or grammar.
        </p>
      </section>
    </>
  );
  return <JobLayout stage={stage} rail={rail} />;
}

function fromJob(job: Job): PostingEdit {
  const p = job.posting;
  return { title: p?.title ?? "", job_description: p?.job_description ?? "", questions: p?.questions ?? [] };
}
