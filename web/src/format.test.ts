import { describe, expect, it } from "vitest";
import { formatClock, formatRupees, formatWhen } from "./format";

const TODAY = new Date(2026, 10, 21, 23, 30); // Sat 21 Nov 2026

describe("formatWhen", () => {
  it("names today and tomorrow, with a 12-hour time", () => {
    expect(formatWhen("2026-11-22 11:00", TODAY)).toBe("Tomorrow, 11 AM");
    expect(formatWhen("2026-11-21 18:30", TODAY)).toBe("Today, 6:30 PM");
  });
  it("gives a weekday within the week and a date beyond it", () => {
    expect(formatWhen("2026-11-24", TODAY)).toBe("Tuesday");
    expect(formatWhen("2026-12-05 09:00", TODAY)).toMatch(/^5 Dec, 9 AM$/);
  });
  it("leaves anything else as it was said", () => {
    expect(formatWhen("after lunch", TODAY)).toBe("after lunch");
  });
});

describe("formatRupees and formatClock", () => {
  it("formats amounts and timers", () => {
    expect(formatRupees("1500")).toBe("₹1,500");
    expect(formatRupees("depends on the work")).toBe("depends on the work");
    expect(formatClock(65)).toBe("1:05");
  });
});
