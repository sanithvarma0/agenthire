// Finding and Providers screens (docs/LLD.md, section 15). The night map takes the stage:
// while the request is read and the search runs it sweeps around the user; then up to 5
// providers appear as glowing dots, the top ranked marked to be called. The list sits in the
// rail; the user can swap who is called, then one tap approves. Nothing is dialled without it.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Clock, MapPin, PhoneCall, Star } from "lucide-react";
import { api, type Job, type Person } from "../api";
import { JobLayout, JobSummary, StepRail } from "../components/Frame";
import { NightMap, type MapPin as Pin } from "../components/NightMap";

export function Finding({ job }: { job: Job }) {
  const start = job.start!;
  const radius = job.search?.radius_km ?? 5;
  const stage = (
    <div className="map-wrap">
      <NightMap center={{ lat: start.lat, lng: start.lng }} radiusKm={radius} pins={[]} marked={[]} focused={null} searching />
      <div className="map-overlay">
        <span className="you-dot" aria-hidden="true" />
        <div>
          <strong>{job.brief ? `Looking for ${plural(job.brief.service)} within ${radius} km` : "Understanding what you need"}</strong>
          <div className="faint small">{job.brief ? "Open now first, then nearest and best reviewed" : "Reading your request…"}</div>
        </div>
      </div>
    </div>
  );
  return <JobLayout stage={stage} rail={<><StepRail job={job} /><JobSummary job={job} /></>} />;
}

export function Providers({ job, onApproved }: { job: Job; onApproved: (job: Job) => void }) {
  const start = job.start!;
  const callTop = job.search?.call_top ?? 2;
  const people = job.people;
  const [marked, setMarked] = useState<string[]>(() => people.slice(0, callTop).map((p) => p.id));
  const [focused, setFocused] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setMarked(people.slice(0, callTop).map((p) => p.id)), [job.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const pins: Pin[] = useMemo(
    () => people.filter((p) => p.lat && p.lng).map((p) => ({ id: p.id, name: p.name, lat: p.lat!, lng: p.lng! })),
    [people],
  );

  const toggle = (id: string) => {
    setHint(null);
    setFocused(id);
    if (marked.includes(id)) return setMarked(marked.filter((m) => m !== id));
    if (marked.length >= callTop) return setHint(`Up to ${callTop} at a time. Untick one to swap.`);
    setMarked([...marked, id]);
  };

  const focus = useCallback((id: string) => {
    setFocused(id);
    document.getElementById(`card-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);

  const approve = async () => {
    if (marked.length === 0) return setHint("Tick at least one to call.");
    setBusy(true);
    try {
      onApproved(await api.approve(job.id, people.filter((p) => marked.includes(p.id)).map((p) => p.id)));
    } catch (err) {
      setHint(`Couldn't start the calls: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const service = job.search?.service ?? job.brief?.service ?? "people";
  const radius = job.search?.radius_km ?? 5;
  const stage = (
    <div className="map-wrap">
      <NightMap center={{ lat: start.lat, lng: start.lng }} radiusKm={radius} pins={pins}
        marked={marked} focused={focused} searching={false} onFocus={focus} />
      <div className="map-overlay">
        <div style={{ flex: 1, minWidth: 0 }}>
          <strong>{people.length} {plural(service, people.length)} within {radius} km</strong>
          <div className="faint small">{job.test_mode ? "Test mode: the calls ring your phone." : "Their phones will ring, one at a time."}</div>
        </div>
        <button className="btn" onClick={approve} aria-busy={busy}>
          <PhoneCall size={17} />{busy ? "Starting…" : marked.length === 1 ? "Call this 1" : `Call these ${marked.length}`}
        </button>
      </div>
    </div>
  );

  const rail = (
    <>
      <StepRail job={job} />
      <section className="panel tight">
        <div className="panel-head">
          <p className="eyebrow">Who to call</p>
          <span className="faint small">Best first · tap to swap</span>
        </div>
        <ul className="plist">
          {people.map((p, i) => (
            <ProviderRow key={p.id} person={p} rank={i + 1} marked={marked.includes(p.id)}
              focused={focused === p.id} onToggle={() => toggle(p.id)} />
          ))}
        </ul>
        {hint && <p className="error" role="alert">{hint}</p>}
      </section>
      <JobSummary job={job} />
    </>
  );
  return <JobLayout stage={stage} rail={rail} />;
}

function ProviderRow({ person, rank, marked, focused, onToggle }: {
  person: Person; rank: number; marked: boolean; focused: boolean; onToggle: () => void;
}) {
  return (
    <li id={`card-${person.id}`}>
      <button className={`pitem ${marked ? "marked" : ""} ${focused ? "focused" : ""}`} onClick={onToggle} aria-pressed={marked}>
        <span className="rank" aria-hidden="true">{rank}</span>
        <span className="who">
          <strong>{person.name}</strong>
          <span className="meta">
            {person.rating != null && <span><Star size={12} fill="currentColor" />{person.rating.toFixed(1)} ({person.review_count ?? 0})</span>}
            {person.distance_km != null && <span><MapPin size={12} />{person.distance_km.toFixed(1)} km</span>}
            {person.open_now === true && <span style={{ color: "var(--good)" }}><Clock size={12} />Open now</span>}
          </span>
        </span>
        <span className="check" aria-hidden="true">{marked && <Check size={15} strokeWidth={3} />}</span>
        <span className="sr-only">{marked ? "Will be called" : "Not selected"}</span>
      </button>
    </li>
  );
}

/** "electrician" to "electricians"; leaves phrases like "AC repair" alone. */
export function plural(service: string, count = 2): string {
  // "Electrician" reads better mid-sentence as "electrician"; "AC repair" stays as it is.
  const s = /^[A-Z][a-z]/.test(service) ? service.charAt(0).toLowerCase() + service.slice(1) : service;
  if (count === 1 || !/[a-z]$/i.test(s) || /repair|service|work$/i.test(s)) return s;
  return /(s|sh|ch|x)$/i.test(s) ? `${s}es` : `${s}s`;
}
