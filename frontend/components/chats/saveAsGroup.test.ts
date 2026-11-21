import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ API_URL: "http://api.test", getAuthHeaders: async () => ({}) }));

import { EMPTY_FILTERS } from "./inboxFilters";
import { MAX_GROUP_PEOPLE, fromChatsBody, savedGroupMessage } from "./saveAsGroup";

describe("fromChatsBody", () => {
  it("carries the name, tab, search and every filter in the list's own words", () => {
    const body = fromChatsBody("  Insta Hot – Nov ", { ...EMPTY_FILTERS, segments: ["A", "B"], cameFrom: ["meta_ads"], tagId: "t-1" }, {
      view: "ai_handling",
      channel: "instagram",
      search: "ravi",
    });
    expect(body).toMatchObject({
      name: "Insta Hot – Nov",
      view: "ai_handling",
      channels: "instagram",
      q: "ravi",
      segments: "A,B",
      came_from: "meta_ads",
      tag_id: "t-1",
    });
  });

  it("leaves out what is not picked", () => {
    const body = fromChatsBody("All", EMPTY_FILTERS, { view: "inbox", channel: "all" });
    expect(body).toEqual({ name: "All", view: "inbox" });
  });
});

describe("savedGroupMessage", () => {
  it("says how many people went where", () => {
    expect(savedGroupMessage(14, "Insta Hot – Nov")).toBe("Saved 14 people to “Insta Hot – Nov”");
    expect(savedGroupMessage(1, "Solo")).toBe("Saved 1 person to “Solo”");
  });
  it("uses Indian digit grouping for big groups", () => {
    expect(savedGroupMessage(1234567, "Big")).toBe("Saved 12,34,567 people to “Big”");
  });
});

describe("limit", () => {
  it("matches the server's cap", () => {
    expect(MAX_GROUP_PEOPLE).toBe(5000);
  });
});
