import { describe, expect, it } from "vitest";
import { appViewFormat, appViewLine, cleanButtonId, nextQuestionsLeft } from "@/components/agents/appView";

describe("App view", () => {
  it("cleans a button id the way the API wants it", () => {
    expect(cleanButtonId("Astrologer")).toBe("astrologer");
    expect(cleanButtonId(" talk to expert ")).toBe("talk_to_expert");
    expect(cleanButtonId("counted")).toBe("");   // a tag the code sets itself
    expect(cleanButtonId("9lives")).toBe("");
    expect(cleanButtonId("")).toBe("");
  });

  it("sends one hand-off button and the questions left", () => {
    expect(appViewFormat("astrologer", 3)).toEqual({
      buttons: [{ id: "astrologer", when: "the question needs a human expert from the business", handoff: true }],
      questions_left: 3,
    });
    expect(appViewFormat("", -2)).toEqual({ buttons: [], questions_left: 0 });
  });

  it("counts a question only on tag counted, never below 0", () => {
    expect(nextQuestionsLeft(3, "counted")).toBe(2);
    expect(nextQuestionsLeft(3, "greeting")).toBe(3);
    expect(nextQuestionsLeft(3, "astrologer")).toBe(3);
    expect(nextQuestionsLeft(0, "counted")).toBe(0);
  });

  it("says what came back", () => {
    expect(appViewLine({ bubbles: ["a", "b"], chips: ["x", "y"], button: "astrologer" }, 3, 2)).toBe(
      "questions left 3 → 2 · 2 bubbles · 2 chips · button",
    );
    expect(appViewLine({ bubbles: ["a"], chips: [], button: null }, 0, 0)).toBe(
      "questions left 0 → 0 · 1 bubble · no chips (0 left)",
    );
  });
});
