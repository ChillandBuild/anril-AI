import { describe, expect, it } from "vitest";
import { docState, tagRows } from "./knowledgeRows";

const tags = [
  { id: "t1", name: "astrology books" },
  { id: "t2", name: "festival offers" },
  { id: "t3", name: "unused" },
];
const docs = [
  { id: "d1", name: "Porutham guide.pdf", status: "processed", created_at: "2026-11-01T10:00:00Z", campaign_tag_id: "t1" },
  { id: "d2", name: "Dasha periods explained.pdf", status: "processed", created_at: "2026-11-09T10:00:00Z", campaign_tag_id: "t1" },
  { id: "d3", name: "Price list.pdf", status: "processed", created_at: "2026-11-02T10:00:00Z", campaign_tag_id: null },
];
const characters = [
  { id: "c1", name: "Jothidar AI", knowledge_tag_id: "t1" },
  { id: "c2", name: "Offer bot", knowledge_tag_id: "t2" },
];

describe("tagRows", () => {
  it("counts files, lists readers, takes the newest date, hides unused tags", () => {
    expect(tagRows(tags, docs, characters)).toEqual([
      { id: "t1", name: "astrology books", files: 2, readBy: ["Jothidar AI"], updated: "2026-11-09T10:00:00Z" },
      { id: "t2", name: "festival offers", files: 0, readBy: ["Offer bot"], updated: null },
    ]);
  });
});

describe("docState", () => {
  it("maps status and sort state", () => {
    expect(docState({ status: "processing" })).toBe("processing");
    expect(docState({ status: "processed", sort_state: "sorting" })).toBe("processing");
    expect(docState({ status: "failed" })).toBe("failed");
    expect(docState({ status: "processed", sort_state: null })).toBe("ready");
  });
});
