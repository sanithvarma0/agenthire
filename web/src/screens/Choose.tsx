// The first page: choose who you are hiring. Gig work at home (an electrician, a plumber)
// or an IT role for a company. Each card is a picture of what that side does and one line.

import { useEffect, useState } from "react";
import { ArrowRight, ChevronRight, Languages, PhoneCall, Quote } from "lucide-react";
import { api, roleOf, type JobSummary } from "../api";
import { GigScene, HireScene } from "../components/Scenes";
import { stepLabel } from "./Start";

export function Choose({ onGig, onIt, onOpen, onHistory }: {
  onGig: () => void; onIt: () => void; onOpen: (jobId: string) => void; onHistory: () => void;
}) {
  const [recent, setRecent] = useState<JobSummary[]>([]);
  useEffect(() => {
    api.recentJobs().then(setRecent).catch(() => setRecent([]));
  }, []);

  return (
    <div className="choose fade-in">
      <header className="choose-head">
        <h1 className="title xl">Who do you need?</h1>
        <p className="muted">Say it. We find, call and shortlist.</p>
      </header>

      <div className="choice-grid">
        <button className="choice gig" onClick={onGig}>
          <GigScene />
          <span className="choice-body">
            <span className="choice-title">Gig worker</span>
            <span className="choice-line">Electrician, plumber, carpenter near you</span>
          </span>
          <span className="choice-go"><ArrowRight size={20} /></span>
        </button>
        <button className="choice it" onClick={onIt}>
          <HireScene />
          <span className="choice-body">
            <span className="choice-title">IT hire</span>
            <span className="choice-line">Engineers and analysts, screened by phone</span>
          </span>
          <span className="choice-go"><ArrowRight size={20} /></span>
        </button>
      </div>

      <ul className="badges" aria-label="What it does">
        <li><Languages size={16} /><span lang="te">తెలుగు</span><span className="faint">·</span><span lang="hi">हिंदी</span><span className="faint">·</span><span>English</span></li>
        <li><PhoneCall size={16} />Real phone calls</li>
        <li><Quote size={16} />Every answer quoted</li>
      </ul>

      {recent.length > 0 && (
        <section className="panel tight choose-recent" aria-labelledby="recent-label">
          <div className="panel-head" style={{ marginBottom: 6 }}>
            <p className="eyebrow" id="recent-label">Recent</p>
            <button className="linkish small" onClick={onHistory}>See all<ChevronRight size={14} /></button>
          </div>
          <ul className="recent">
            {recent.slice(0, 4).map((j) => (
              <li key={j.id}>
                <button onClick={() => onOpen(j.id)}>
                  <span className={`side-dot ${j.side === "company" ? "it" : "gig"}`} aria-hidden="true" />
                  <span className="what">{roleOf(j)?.role ?? j.brief?.work ?? j.request ?? "Voice request"}</span>
                  <span className={`chip ${j.status === "failed" ? "bad" : j.step === "done" ? "good" : ""}`}>
                    {j.status === "failed" ? "Didn't finish" : stepLabel(j.step, j.side === "company")}
                  </span>
                  <ChevronRight size={16} className="faint" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
