// Turning call results into words for the screen.

export const OUTCOME_LABELS: Record<string, string> = {
  available: "Can come",
  not_available: "Can't come",
  wrong_number: "Wrong number",
  call_customer: "Wants to talk to you",
  declined: "Declined",
  no_answer: "No answer",
  interested: "Interested",
  not_interested: "Not interested",
  call_later: "Call later",
};

/** Outcomes that mean the person is taking part (a provider who can come, an interested candidate). */
export const GOOD_OUTCOMES = new Set(["available", "interested"]);

const DAY = 24 * 60 * 60 * 1000;

/** "2026-11-22 11:00" as "Tomorrow, 11 AM"; a date alone as "Tomorrow"; anything else as given. */
export function formatWhen(value: string, today: Date = new Date()): string {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?$/);
  if (!match) return value;
  const [, y, mo, d, h, mi] = match;
  const date = new Date(Number(y), Number(mo) - 1, Number(d));
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((date.getTime() - start.getTime()) / DAY);
  const day =
    days === 0 ? "Today" : days === 1 ? "Tomorrow"
      : days > 1 && days < 7 ? date.toLocaleDateString("en-IN", { weekday: "long" })
        : date.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  if (h === undefined) return day;
  const hour = Number(h);
  const minutes = mi === "00" ? "" : `:${mi}`;
  const suffix = hour < 12 ? "AM" : "PM";
  return `${day}, ${hour % 12 || 12}${minutes} ${suffix}`;
}

/** "500" as "₹500"; anything that is not a plain number as given. */
export function formatRupees(value: string): string {
  return /^\d+(\.\d+)?$/.test(value.trim()) ? `₹${Number(value).toLocaleString("en-IN")}` : value;
}

/** Seconds as "1:05". */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
