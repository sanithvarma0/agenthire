// Confirming and Scheduled screens (docs/LLD.md, section 15). While confirming, the call
// back to the chosen provider is shown live, like the enquiry calls. Once they confirm, the
// job is scheduled: a booking ticket with who, when, the charge, the address, and the SMS
// that went to them with the address.

import { Check, MessageSquare, Phone, RotateCcw } from "lucide-react";
import { type Job, type JobEvent } from "../api";
import { JobLayout, JobSummary, StepRail } from "../components/Frame";
import { formatRupees, formatWhen } from "../format";
import { useJob } from "../store";
import { CallPanel } from "./Calls";

export function Confirming({ job }: { job: Job }) {
  const events = useJob((s) => s.events);
  const person = job.people.find((p) => p.id === job.report?.picked_person_id);
  const conversation = job.conversations
    .filter((c) => c.kind === "confirm_call" && c.person_id === person?.id).at(-1) ?? null;
  if (!person) return null;
  const stage = (
    <>
      <div>
        <p className="eyebrow accent" style={{ marginBottom: 8 }}>Booking</p>
        <h1 className="title lg">Confirming with <span className="accent">{person.name}</span></h1>
        <p className="muted" style={{ margin: "8px 0 0" }}>Calling back to fix the visit. The address goes to them by SMS once they confirm.</p>
      </div>
      <CallPanel person={person} conversation={conversation} events={events} factNames={["visit_time"]} />
    </>
  );
  return <JobLayout stage={stage} rail={<><StepRail job={job} /><JobSummary job={job} /></>} />;
}

export function Scheduled({ job, onRestart }: { job: Job; onRestart: () => void }) {
  const events = useJob((s) => s.events);
  const booking = job.report?.booking;
  const person = job.people.find((p) => p.id === booking?.person_id);
  if (!booking || !person) return null;
  const when = booking.visit_time ? formatWhen(booking.visit_time) : "Time to be confirmed";
  const moved = booking.offered_time && booking.visit_time && booking.offered_time !== booking.visit_time;
  const sms = [...events].reverse().find((e: JobEvent) => e.type === "message_sent" && e.payload.person_id === person.id);
  const message = (job.messages as { body?: string; status?: string; routed_to?: string }[]).at(-1);
  const sent = (message?.status ?? booking.sms_status) === "sent";

  const stage = (
    <>
      <section className="ticket fade-in">
        <div className="ticket-top">
          <div className="tick-big" aria-hidden="true"><Check size={30} strokeWidth={3} /></div>
          <p className="eyebrow" style={{ color: "var(--good)", margin: "6px 0 0" }}>Scheduled</p>
          <h1 className="title lg">{person.name}</h1>
          <p className="title md accent">{when}</p>
          {moved && <p className="faint small" style={{ margin: 0 }}>They moved it from {formatWhen(booking.offered_time!)}.</p>}
        </div>
        <div className="ticket-cut" aria-hidden="true" />
        <div className="ticket-bottom">
          <dl className="kv">
            <dt>Visit charge</dt><dd>{booking.visiting_charge ? formatRupees(booking.visiting_charge) : "Not said"}</dd>
            <dt>Phone</dt><dd><a href={`tel:${person.phone}`} className="row" style={{ gap: 6, display: "inline-flex" }}><Phone size={13} />{person.phone}</a></dd>
            <dt>Address</dt><dd>{booking.address}</dd>
          </dl>
          <div className="stack">
            <p className="eyebrow row" style={{ gap: 6 }}><MessageSquare size={13} />{sent ? "Address sent by SMS" : "SMS not sent"}</p>
            <pre className="sms">{message?.body ?? String(sms?.payload.body ?? "")}</pre>
            <p className="faint small" style={{ margin: 0 }}>
              {sent
                ? message?.routed_to ? `Sent to your phone (test mode), not to ${person.name}.` : `Sent to ${person.name}.`
                : `It could not be sent (${message?.status ?? booking.sms_status}). Tell them the address when they call.`}
            </p>
          </div>
        </div>
      </section>
      <button className="btn ghost" onClick={onRestart}><RotateCcw size={16} />Book something else</button>
    </>
  );
  return <JobLayout stage={stage} rail={<><StepRail job={job} /><JobSummary job={job} /></>} />;
}
