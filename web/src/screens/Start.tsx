// Start screen (docs/LLD.md, section 15). Left, what AgentHire does; right, the two things
// it needs before talking: the language and where the work is (prefilled from the browser
// location, plus the house number). Then the voice brief, or a typed request.

import { useEffect, useState } from "react";
import { ArrowRight, ChevronRight, Keyboard, LocateFixed, Mic, Scale, Search } from "lucide-react";
import { api, roleOf, spokenArea, type Area, type JobSummary, type Language } from "../api";

const LANGUAGES: { code: Language; native: string; english: string }[] = [
  { code: "te", native: "తెలుగు", english: "Telugu" },
  { code: "hi", native: "हिंदी", english: "Hindi" },
  { code: "en", native: "English", english: "English" },
];

type Place =
  | { status: "asking" }
  | { status: "looking-up"; lat: number; lng: number }
  | { status: "ready"; lat: number; lng: number }
  | { status: "failed"; reason: string };

export function Start({ onStarted, onHistory }: { onStarted: (jobId: string) => void; onHistory: () => void }) {
  const [language, setLanguage] = useState<Language | null>(null);
  const [place, setPlace] = useState<Place>({ status: "asking" });
  const [area, setArea] = useState<Area>({ colony: "", locality: "", city: "" });
  const [street, setStreet] = useState("");
  const [house, setHouse] = useState("");
  const [request, setRequest] = useState("");
  const [typing, setTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<JobSummary[]>([]);

  const locate = () => {
    if (!("geolocation" in navigator)) {
      setPlace({ status: "failed", reason: "This browser can't share its location." });
      return;
    }
    setPlace({ status: "asking" });
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        const { latitude: lat, longitude: lng } = coords;
        setPlace({ status: "looking-up", lat, lng });
        try {
          const found = await api.location(lat, lng);
          setArea(found.area);
          setStreet(found.street_address);
          setPlace({ status: "ready", lat, lng });
        } catch {
          setPlace({ status: "failed", reason: "Couldn't look up this location. Try again." });
        }
      },
      (err) =>
        setPlace({
          status: "failed",
          reason: err.code === err.PERMISSION_DENIED
            ? "Location is blocked. Allow it for this site to find people near you."
            : "Couldn't get your location. Try again.",
        }),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    );
  };

  useEffect(() => {
    locate();
    api.recentJobs().then(setRecent).catch(() => setRecent([]));
  }, []);

  const start = async (byVoice: boolean) => {
    setError(null);
    if (!language) return setError("Choose a language first.");
    if (place.status !== "ready") return setError("Your location is needed to find people nearby.");
    if (!house.trim()) return setError("Add your house or flat number.");
    if (!street.trim()) return setError("Add your street address.");
    if (!byVoice && request.trim().length < 4) return setError("Say what needs fixing.");
    setBusy(true);
    try {
      const job = await api.startJob({
        language,
        address: `${house.trim()}, ${street.trim()}`,
        lat: place.lat,
        lng: place.lng,
        area: spokenArea(area),
        request: byVoice ? null : request.trim(),
      });
      onStarted(job.id);
    } catch (err) {
      setError(`Couldn't start: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="job start fade-in">
      <section className="hero-stage" aria-labelledby="hero-title">
        <div>
          <p className="eyebrow accent" style={{ marginBottom: 12 }}>Your helper for home repairs</p>
          <h1 className="title xl" id="hero-title">
            Say what's broken.<br /><span className="accent">We'll call around.</span>
          </h1>
          <p className="muted" style={{ margin: "14px 0 0", maxWidth: 520 }}>
            Tell the assistant what needs fixing. It finds people near you, phones them in their
            language, and brings back who can come, when and for how much.
          </p>
          <div className="langs-line">
            {LANGUAGES.map((l) => <span key={l.code} className="chip" lang={l.code}>{l.native}</span>)}
          </div>
        </div>
        <div className="divider" />
        <ol className="flow" aria-label="How it works">
          <li><span className="tile"><Mic size={20} /></span>
            <div><strong>You tell the assistant</strong><span>Talk to it face to face, in your language. It asks what a repair person would need to know.</span></div></li>
          <li><span className="tile"><Search size={20} /></span>
            <div><strong>It finds and calls people near you</strong><span>Real shops from the map, best rated and nearest first. You approve who gets a call.</span></div></li>
          <li><span className="tile"><Scale size={20} /></span>
            <div><strong>You choose, it books</strong><span>Who can come, when and the charge, in their own words. One tap confirms the visit and sends your address.</span></div></li>
        </ol>
      </section>

      <aside className="rail">
        <section className="panel" aria-labelledby="lang-label">
          <p className="eyebrow" id="lang-label" style={{ marginBottom: 10 }}>1 · Your language</p>
          <div className="segmented">
            {LANGUAGES.map((l) => (
              <button key={l.code} className="seg" aria-pressed={language === l.code} onClick={() => setLanguage(l.code)}>
                <span className="native" lang={l.code}>{l.native}</span>
                <span className="en">{l.english}</span>
              </button>
            ))}
          </div>

          <div className="divider" style={{ margin: "18px 0" }} />
          <p className="eyebrow" style={{ marginBottom: 10 }}>2 · Where the work is</p>
          {place.status === "asking" || place.status === "looking-up" ? (
            <div className="locating"><span className="you-dot" aria-hidden="true" />Finding where you are…</div>
          ) : place.status === "failed" ? (
            <div className="stack">
              <p className="muted small" style={{ margin: 0 }}>{place.reason}</p>
              <button className="btn ghost sm" onClick={locate} style={{ justifySelf: "start" }}><LocateFixed size={15} />Try again</button>
            </div>
          ) : (
            <div className="stack">
              <div className="row"><span className="you-dot" aria-hidden="true" /><strong>{spokenArea(area)}</strong></div>
              <label className="field"><span>House or flat number</span>
                <input value={house} onChange={(e) => setHouse(e.target.value)} placeholder="Flat 302, Sai Residency" />
              </label>
              <label className="field"><span>Street</span>
                <input value={street} onChange={(e) => setStreet(e.target.value)} />
              </label>
              <label className="field"><span>Colony (as you'd say it on the phone)</span>
                <input value={area.colony} onChange={(e) => setArea({ ...area, colony: e.target.value })} />
              </label>
            </div>
          )}

          <div className="divider" style={{ margin: "18px 0" }} />
          {typing ? (
            <div className="stack">
              <label className="field"><span>What needs fixing</span>
                <textarea value={request} onChange={(e) => setRequest(e.target.value)}
                  placeholder="The kitchen light flickers and one plug point isn't working" />
              </label>
              <button className="btn lg block" onClick={() => start(false)} aria-busy={busy}>
                {busy ? "Starting…" : <>Find people near me <ArrowRight size={18} /></>}
              </button>
              <button className="linkish" onClick={() => setTyping(false)}><Mic size={15} />Talk instead</button>
            </div>
          ) : (
            <div className="stack">
              <button className="btn lg block" onClick={() => start(true)} aria-busy={busy}>
                <Mic size={19} />{busy ? "Starting…" : "Talk to your assistant"}
              </button>
              <button className="linkish" onClick={() => setTyping(true)} style={{ justifySelf: "center" }}>
                <Keyboard size={15} />or type it instead
              </button>
            </div>
          )}
          {error && <p className="error" role="alert">{error}</p>}
        </section>

        {recent.length > 0 && (
          <section className="panel tight" aria-labelledby="recent-label">
            <div className="panel-head" style={{ marginBottom: 6 }}>
              <p className="eyebrow" id="recent-label">Recent</p>
              <button className="linkish small" onClick={onHistory}>See all<ChevronRight size={14} /></button>
            </div>
            <ul className="recent">
              {recent.slice(0, 5).map((j) => (
                <li key={j.id}>
                  <button onClick={() => onStarted(j.id)}>
                    <span className="what">{roleOf(j) ? `Hiring: ${roleOf(j)!.role}` : j.brief?.work ?? j.request ?? "Voice request"}</span>
                    <span className={`chip ${j.status === "failed" ? "bad" : j.step === "done" ? "good" : ""}`}>
                      {j.status === "failed" ? "Didn't finish" : stepLabel(j.step)}
                    </span>
                    <ChevronRight size={16} className="faint" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>
    </div>
  );
}

export function stepLabel(step: string): string {
  return ({
    briefing: "Started", finding: "Finding", awaiting_approval: "Pick who to call", calling: "Calling",
    reporting: "Comparing", awaiting_pick: "Choose one", confirming: "Confirming", done: "Scheduled",
  } as Record<string, string>)[step] ?? step;
}
