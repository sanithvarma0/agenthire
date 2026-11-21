import { describe, expect, it } from "vitest";
import { spokenArea } from "./api";

describe("spokenArea", () => {
  it("joins colony, locality and city", () => {
    expect(spokenArea({ colony: "Indira Nagar", locality: "Gachibowli", city: "Hyderabad" }))
      .toBe("Indira Nagar, Gachibowli, Hyderabad");
  });
  it("drops empty and repeated parts", () => {
    expect(spokenArea({ colony: "", locality: "Hyderabad", city: "Hyderabad" })).toBe("Hyderabad");
  });
});
