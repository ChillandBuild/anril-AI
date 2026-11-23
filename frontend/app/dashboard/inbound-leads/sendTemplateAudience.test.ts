import { describe, expect, it } from "vitest";
import { audienceWords } from "./SendTemplateAudience";

describe("Send template: who gets it, in plain words", () => {
  it("says the result, interest and when", () => {
    expect(audienceWords("", "booked", "30")).toBe("Booked customers, any interest, who came in the last 30 days.");
    expect(audienceWords("A", "", "any")).toBe("Everyone, Hot interest, who came at any time.");
  });
});
