// The job being shown and its live events. The job's step decides the screen;
// the event stream keeps it current, so a reload lands on the same screen.

import { create } from "zustand";
import { api, type Job, type JobEvent } from "./api";

interface JobState {
  jobId: string | null;
  job: Job | null;
  events: JobEvent[];
  lastSeq: number;
  connected: boolean;
  error: string | null;
  open: (jobId: string) => Promise<void>;
  close: () => void;
  refresh: () => Promise<void>;
}

let source: EventSource | null = null;

// Events after which the job itself (step, people, results) has changed.
const REFRESH_ON = new Set([
  "step_changed", "conversation_started", "call_routed", "guardrail_blocked", "conversation_ended", "result_ready",
  "message_sent",
]);

export const useJob = create<JobState>((set, get) => ({
  jobId: null,
  job: null,
  events: [],
  lastSeq: 0,
  connected: false,
  error: null,

  open: async (jobId) => {
    get().close();
    set({ jobId, job: null, events: [], lastSeq: 0, error: null });
    try {
      set({ job: await api.job(jobId) });
    } catch (err) {
      set({ error: (err as Error).message });
      return;
    }
    // The stream replays stored events first, then sends new ones as they happen.
    source = new EventSource(`/events/stream?job_id=${encodeURIComponent(jobId)}`);
    source.onopen = () => set({ connected: true });
    source.onerror = () => set({ connected: false });
    source.onmessage = (msg) => {
      let event: JobEvent;
      try {
        event = JSON.parse(msg.data) as JobEvent;
      } catch {
        return;
      }
      if (event.seq <= get().lastSeq) return; // already seen (a reconnect replays)
      set((s) => ({ events: [...s.events, event], lastSeq: event.seq }));
      if (REFRESH_ON.has(event.type)) void get().refresh();
    };
  },

  close: () => {
    source?.close();
    source = null;
    set({ connected: false });
  },

  refresh: async () => {
    const id = get().jobId;
    if (!id) return;
    try {
      set({ job: await api.job(id) });
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },
}));
