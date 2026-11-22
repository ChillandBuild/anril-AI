import { describe, expect, it } from "vitest";
import { SENT_STATUS, notSentBanner } from "./sentText";

describe("Sent page text", () => {
  it("banner counts and keeps the promise", () => {
    expect(notSentBanner(1)).toBe(
      "1 message didn't go out today. Each one shows the reason in plain words and what to do. Nothing is sent twice."
    );
    expect(notSentBanner(4).startsWith("4 messages didn't go out today.")).toBe(true);
  });

  it("has a pill for every status", () => {
    expect(Object.keys(SENT_STATUS).sort()).toEqual(["delivered", "not_sent", "read", "sent", "will_retry"]);
  });
});
