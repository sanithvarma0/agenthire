// Types and calls for the AgentHire back end (docs/LLD.md, section 8).
// The dev server and the deployed site both serve the API on the same origin.

export type Language = "te" | "hi" | "en";

export interface Area {
  colony: string;
  locality: string;
  city: string;
}

export interface Location {
  area: Area;
  street_address: string;
}

export interface JobStart {
  language: Language;
  address: string;
  lat: number;
  lng: number;
  area: string;
  request?: string | null;
  company?: string; // company jobs only; they have no address, area or location
}

export interface Person {
  id: string;
  name: string;
  phone: string | null;
  rating: number | null;
  review_count: number | null;
  address: string | null;
  distance_km: number | null;
  lat?: number;
  lng?: number;
  open_now?: boolean | null;
  maps_url?: string;
  approved: boolean;
  source?: string; // "google_places"; company side: "web" (sourced, display only) or "applied"
  headline?: string;
  company?: string;
  location?: string;
  experience?: string;
  profile_url?: string;
}

export interface Brief {
  service: string;
  work: string;
}

/** A company job's brief: the role as understood (it sits in `job.brief`; see roleOf). */
export interface RoleBrief {
  role: string;
  company: string;
  must_haves: string[];
  experience: string;
  location: string;
  summary: string;
}

export interface ScreeningQuestion {
  question: string;
  strong: string;
  average: string;
  weak: string;
}

export interface Posting {
  title: string;
  job_description: string;
  questions: ScreeningQuestion[];
  approved_at?: string | null;
}

export type PostingEdit = Omit<Posting, "approved_at">;

/** The role of a company job, or null for a home job. */
export function roleOf(job: { side?: string; brief: unknown }): RoleBrief | null {
  return job.side === "company" && job.brief ? (job.brief as RoleBrief) : null;
}

export interface Search {
  service: string;
  radius_km: number;
  area: Area;
  call_top: number;
  sourced?: { found: number; error: string | null; seconds?: number }; // company side
}

export interface Report {
  recommended_person_id: string | null;
  reasoning: string;
  picked_person_id?: string;
  unavailable?: string[];
  notice?: string;
  booking?: Booking;
}

export interface Booking {
  person_id: string;
  visit_time: string | null;
  offered_time: string | null;
  visiting_charge: string | null;
  address: string;
  conversation_id: string;
  sms_status: string;
}

export interface CallFact {
  name: string;
  value: string;
  said_as: string;
  verified: boolean | null;
}

export interface CallResultView {
  outcome: string;
  facts: CallFact[];
  notes: string;
}

export interface Conversation {
  id: string;
  person_id: string | null;
  kind: string;
  language: string;
  status: string;
  result: CallResultView | null;
  routed_to: string | null;
}

export interface Job {
  id: string;
  side: "home" | "company";
  posting: Posting | null;
  step: string;
  status: string;
  error: string | null;
  start: JobStart | null;
  brief: Brief | null;
  search: Search | null;
  report: Report | null;
  created_at: string;
  people: Person[];
  conversations: Conversation[];
  messages: Record<string, unknown>[];
  test_mode: boolean;
}

export interface JobSummary {
  id: string;
  side: "home" | "company";
  company: string | null;
  step: string;
  status: string;
  created_at: string;
  request: string | null;
  area: string | null;
  brief: Brief | null;
  language: string | null;
  error: string | null;
  found: number;
  called: number;
  available: number;
  booked: { name: string | null; visit_time: string | null; visiting_charge: string | null } | null;
}

export interface JobEvent {
  id: number;
  job_id: string;
  conversation_id: string | null;
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status code */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  location: (lat: number, lng: number) => call<Location>(`/location?lat=${lat}&lng=${lng}`),
  startJob: (start: JobStart) => call<Job>("/jobs", { method: "POST", body: JSON.stringify(start) }),
  job: (id: string) => call<Job>(`/jobs/${encodeURIComponent(id)}`),
  recentJobs: () => call<JobSummary[]>("/jobs"),
  history: () => call<JobSummary[]>("/jobs?limit=100"),
  startRole: (company: string, request: string | null) =>
    call<Job>("/roles", { method: "POST", body: JSON.stringify({ company, request }) }),
  savePosting: (id: string, posting: PostingEdit) =>
    call<Job>(`/roles/${encodeURIComponent(id)}/posting`, { method: "PUT", body: JSON.stringify(posting) }),
  approvePosting: (id: string, posting: PostingEdit) =>
    call<Job>(`/roles/${encodeURIComponent(id)}/posting/approve`, { method: "POST", body: JSON.stringify(posting) }),
  approve: (id: string, personIds: string[]) =>
    call<Job>(`/jobs/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ person_ids: personIds }) }),
  voice: (id: string) =>
    call<{ url: string; token: string; room: string }>(`/jobs/${encodeURIComponent(id)}/voice`, { method: "POST" }),
  skip: (id: string) => call<{ skipping: string }>(`/jobs/${encodeURIComponent(id)}/skip`, { method: "POST" }),
  pick: (id: string, personId: string) =>
    call<Job>(`/jobs/${encodeURIComponent(id)}/pick`, { method: "POST", body: JSON.stringify({ person_id: personId }) }),
  stop: (id: string) => call<{ stopping: boolean }>(`/jobs/${encodeURIComponent(id)}/stop`, { method: "POST" }),
};

/** Colony, locality and city without repeats, as the agent says it on calls. */
export function spokenArea(area: Area): string {
  return [area.colony, area.locality, area.city].filter((part, i, all) => part && all.indexOf(part) === i).join(", ");
}
