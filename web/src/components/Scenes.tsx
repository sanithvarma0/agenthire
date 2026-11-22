// Illustrations for the start screens: small drawn widgets that show what each side does,
// so the page needs few words. They are pictures only: nothing in them is live data, and they
// are hidden from screen readers (the text beside them says the same thing).

import type { ComponentType } from "react";
import { Check, FileText, Hammer, Phone, Quote, Wrench, Zap } from "lucide-react";

type Icon = ComponentType<{ size?: number; strokeWidth?: number }>;

const PINS: { x: number; y: number; icon: Icon; on?: boolean }[] = [
  { x: 66, y: 42, icon: Zap, on: true },
  { x: 24, y: 30, icon: Wrench },
  { x: 80, y: 70, icon: Hammer },
];

/** Gig work: a night map with people nearby, one being called, and what they said. */
export function GigScene({ size = "md" }: { size?: "sm" | "md" }) {
  return (
    <div className={`scene gig ${size}`} aria-hidden="true">
      <svg className="scene-map" viewBox="0 0 400 240" preserveAspectRatio="xMidYMid slice">
        <path d="M-10 170 C 80 150, 140 200, 230 175 S 360 120, 420 140" className="river" />
        <path d="M0 70 H400 M0 130 H400 M0 205 H400 M60 0 V240 M150 0 V240 M255 0 V240 M335 0 V240" className="street" />
        <path d="M0 20 L180 240 M210 0 L400 190" className="street wide" />
        <rect x="165" y="80" width="70" height="38" rx="6" className="block" />
        <rect x="270" y="150" width="52" height="40" rx="6" className="block" />
        <rect x="75" y="145" width="58" height="46" rx="6" className="block" />
        <path d="M200 120 Q 236 92 264 101" className="route" />
      </svg>
      <span className="scene-you" style={{ left: "50%", top: "50%" }} />
      {PINS.map(({ x, y, icon: I, on }) => (
        <span key={`${x}-${y}`} className={`scene-pin ${on ? "on" : ""}`} style={{ left: `${x}%`, top: `${y}%` }}>
          <I size={14} strokeWidth={2.4} />
        </span>
      ))}
      <div className="scene-card call">
        <span className="scene-ic good"><Phone size={13} strokeWidth={2.4} /></span>
        <span className="bars on"><span /><span /><span /><span /><span /></span>
        <span className="scene-time">0:42</span>
      </div>
      <div className="scene-card result">
        <span className="scene-ic good"><Check size={13} strokeWidth={2.6} /></span>
        <span><strong>Tomorrow 11 AM</strong><em>₹200 visit</em></span>
      </div>
    </div>
  );
}

const ROWS = [
  { initials: "AK", score: "4.6", bar: 86, top: true },
  { initials: "PR", score: "4.1", bar: 70 },
  { initials: "SM", score: "3.4", bar: 52 },
];

/** IT hiring: a written job description, and a shortlist scored with the candidate's own words. */
export function HireScene({ size = "md" }: { size?: "sm" | "md" }) {
  return (
    <div className={`scene hire ${size}`} aria-hidden="true">
      <div className="scene-jd">
        <div className="row" style={{ gap: 8 }}>
          <span className="scene-ic blue"><FileText size={13} strokeWidth={2.4} /></span>
          <span className="scene-line strong" style={{ width: "58%" }} />
        </div>
        <span className="scene-line" style={{ width: "92%" }} />
        <span className="scene-line" style={{ width: "78%" }} />
        <div className="scene-qs">
          {[1, 2, 3, 4, 5].map((n) => <span key={n}>Q{n}</span>)}
        </div>
      </div>
      <div className="scene-list">
        {ROWS.map((r) => (
          <div key={r.initials} className={`scene-row ${r.top ? "top" : ""}`}>
            <span className="scene-face">{r.initials}</span>
            <span className="scene-meter"><span style={{ width: `${r.bar}%` }} /></span>
            <span className="scene-score">{r.score}</span>
          </div>
        ))}
        <div className="scene-quote">
          <Quote size={12} strokeWidth={2.4} />
          <span className="scene-line" style={{ width: "80%" }} />
        </div>
      </div>
    </div>
  );
}

/** A row of steps, each an icon and two or three words. */
export function StepStrip({ steps, tone = "brand" }: { steps: { icon: Icon; label: string }[]; tone?: "brand" | "blue" }) {
  return (
    <ol className={`step-strip ${tone}`} aria-label="How it works">
      {steps.map(({ icon: I, label }, i) => (
        <li key={label}>
          <span className="tile"><I size={18} /></span>
          <span className="label"><span className="n">{i + 1}</span>{label}</span>
        </li>
      ))}
    </ol>
  );
}
