import { describe, expect, it } from "vitest";
import { buttonPattern, isComplete, moveCard, shapeProblems, type CarouselCardShape } from "./carousel-rules";

const card = (o: Partial<CarouselCardShape> = {}): CarouselCardShape => ({
  header_media_type: "IMAGE",
  header_media_url: "https://example.com/a.jpg",
  body_text: "Soft silk · ₹2,450",
  buttons: [{ type: "URL", text: "Order" }, { type: "QUICK_REPLY", text: "Ask price" }],
  ...o,
});

describe("carousel rules", () => {
  it("counts a card once it has media and text", () => {
    expect(isComplete(card())).toBe(true);
    expect(isComplete(card({ header_media_url: " " }))).toBe(false);
  });

  it("compares button types in order, not their words", () => {
    expect(buttonPattern(card())).toBe("URL+QUICK_REPLY");
    expect(buttonPattern(card({ buttons: [{ type: "URL", text: "" }] }))).toBe("");
  });

  it("flags mixed media and mixed buttons across finished cards only", () => {
    expect(shapeProblems([card(), card({ buttons: [{ type: "URL", text: "Buy" }, { type: "QUICK_REPLY", text: "Price?" }] })])).toEqual({ media: false, buttons: false });
    expect(shapeProblems([card(), card({ header_media_type: "VIDEO" })]).media).toBe(true);
    expect(shapeProblems([card(), card({ buttons: [{ type: "URL", text: "Order" }] })]).buttons).toBe(true);
    expect(shapeProblems([card(), card({ header_media_type: "VIDEO", header_media_url: "" })]).media).toBe(false);
  });

  it("moves a card left or right and stays put at the ends", () => {
    expect(moveCard(["a", "b", "c"], 1, -1)).toEqual(["b", "a", "c"]);
    expect(moveCard(["a", "b", "c"], 2, 1)).toEqual(["a", "b", "c"]);
  });
});
