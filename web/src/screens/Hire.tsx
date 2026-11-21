// Hire screen (docs/LLD.md, section 17): the company side's start. Left, what AgentHire does
// for a hiring team; right, the company's name, then the role by voice or typed.

import { useState } from "react";
import { ArrowRight, Building2, FileText, Keyboard, ListChecks, Mic, PhoneCall } from "lucide-react";
import { api } from "../api";

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
          <p className="eyebrow accent" style={{ marginBottom: 12 }}>For hiring teams</p>
          <h1 className="title xl" id="hire-title">
            Describe the role.<br /><span className="accent">We'll find and screen candidates.</span>
          </h1>
          <p className="muted" style={{ margin: "14px 0 0", maxWidth: 520 }}>
            Tell the assistant who you need. It writes the job description and the screening questions, crawls the
            web for people who fit, phones the ones you pick for a first screen, and ranks them with their own words as proof.
          </p>
        </div>
        <div className="divider" />
        <ol className="flow" aria-label="How it works">
          <li><span className="tile"><FileText size={20} /></span>
            <div><strong>You describe the role</strong><span>By voice or typed. You check the job description and the questions before anything goes out.</span></div></li>
          <li><span className="tile"><PhoneCall size={20} /></span>
            <div><strong>It screens the candidates you pick by phone</strong><span>A short first call in English that understands Hindi or Telugu mixed in. You choose who gets called.</span></div></li>
          <li><span className="tile"><ListChecks size={20} /></span>
            <div><strong>You get a ranked shortlist</strong><span>Every score quotes what the candidate said, judged on content, never on accent.</span></div></li>
        </ol>
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
