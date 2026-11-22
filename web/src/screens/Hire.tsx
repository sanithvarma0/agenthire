// IT hire screen (docs/LLD.md, section 17): the company side's start. Left, a picture of what
// happens; right, the company's name, then the role by voice or typed.

import { useState } from "react";
import { ArrowRight, Building2, FileText, Globe, Keyboard, ListChecks, Mic, PhoneCall } from "lucide-react";
import { api } from "../api";
import { HireScene, StepStrip } from "../components/Scenes";

const COMPANY_KEY = "agenthire.company";

function savedCompany(): string {
  try {
    return localStorage.getItem(COMPANY_KEY) ?? "";
  } catch {
    return "";
  }
}

export function Hire({ onStarted }: { onStarted: (jobId: string) => void }) {
  const [company, setCompany] = useState(savedCompany);
  const [request, setRequest] = useState("");
  const [typing, setTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async (byVoice: boolean) => {
    setError(null);
    if (company.trim().length < 2) return setError("Add the company's name.");
    if (!byVoice && request.trim().length < 4) return setError("Describe the role.");
    setBusy(true);
    try {
      try {
        localStorage.setItem(COMPANY_KEY, company.trim());
      } catch {
        /* remembering the name is only a convenience */
      }
      const job = await api.startRole(company.trim(), byVoice ? null : request.trim());
      onStarted(job.id);
    } catch (err) {
      setError(`Couldn't start: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="job start fade-in">
      <section className="hero-stage" aria-labelledby="hire-title">
        <div>
          <p className="eyebrow blue" style={{ marginBottom: 12 }}>IT hire</p>
          <h1 className="title xl" id="hire-title">
            Describe the role.<br /><span className="blue">We'll screen candidates.</span>
          </h1>
        </div>
        <HireScene />
        <StepStrip tone="blue" steps={[
          { icon: FileText, label: "Job description" },
          { icon: Globe, label: "Web crawl" },
          { icon: PhoneCall, label: "Screening call" },
          { icon: ListChecks, label: "Shortlist" },
        ]} />
      </section>

      <aside className="rail">
        <section className="panel">
          <p className="eyebrow" style={{ marginBottom: 10 }}>1 · Your company</p>
          <label className="field"><span>Company name (as said on calls)</span>
            <span className="input-icon"><Building2 size={16} className="faint" />
              <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme Labs" />
            </span>
          </label>

          <div className="divider" style={{ margin: "18px 0" }} />
          <p className="eyebrow" style={{ marginBottom: 10 }}>2 · The role</p>
          {typing ? (
            <div className="stack">
              <label className="field"><span>Who you're hiring</span>
                <textarea value={request} onChange={(e) => setRequest(e.target.value)} rows={5}
                  placeholder="A backend engineer with 3+ years of Python and APIs, in Hyderabad, hybrid" />
              </label>
              <button className="btn lg block" onClick={() => start(false)} aria-busy={busy}>
                {busy ? "Starting…" : <>Write the job description <ArrowRight size={18} /></>}
              </button>
              <button className="linkish" onClick={() => setTyping(false)} style={{ justifySelf: "center" }}>
                <Mic size={15} />Talk instead
              </button>
            </div>
          ) : (
            <div className="stack">
              <button className="btn lg block" onClick={() => start(true)} aria-busy={busy}>
                <Mic size={19} />{busy ? "Starting…" : "Describe it to the assistant"}
              </button>
              <button className="linkish" onClick={() => setTyping(true)} style={{ justifySelf: "center" }}>
                <Keyboard size={15} />or type it instead
              </button>
            </div>
          )}
          {error && <p className="error" role="alert">{error}</p>}
        </section>
      </aside>
    </div>
  );
}
