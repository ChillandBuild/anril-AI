import { describe, expect, it } from "vitest";
import {
  NO_FILTERS,
  filterTemplates,
  isStaffAlertMarketing,
  languageOptions,
  plainRejection,
  statusNote,
  usedInOptions,
  usedInText,
} from "./template-filters";
import { countsText, downloadRows, typeName } from "./template-excel";
import type { Template, TemplateUsage } from "./types";

const tpl = (id: string, over: Partial<Template> = {}): Template => ({
  id,
  name: `tpl_${id}`,
  category: "UTILITY",
  language: "en",
  body_text: "Hello there",
  status: "APPROVED",
  ...over,
});

const usage: TemplateUsage = {
  a: [{ area: "follow_ups", label: "Follow-ups", href: "/dashboard/settings/follow-ups" }],
  b: [{ area: "reach", label: "was in Reach · ended", href: "/dashboard/outbound-leads", ended: true }],
  c: [{ area: "staff_alert", label: "Alert to staff", href: "/dashboard/settings" }],
};

const list = [
  tpl("a"),
  tpl("b", { language: "ta", category: "MARKETING" }),
  tpl("c", { language: "hi", category: "MARKETING" }),
  tpl("d", { language: "ta", status: "REJECTED", rejection_reason: "INVALID_FORMAT" }),
];

const ids = (rows: Template[]) => rows.map((t) => t.id);

describe("language filter", () => {
  it("keeps only that language", () => {
    expect(ids(filterTemplates(list, { ...NO_FILTERS, language: "ta" }, usage))).toEqual(["b", "d"]);
  });

  it("builds the choices from the languages present, by name", () => {
    expect(languageOptions(list)).toEqual([
      { value: "en", label: "English" },
      { value: "hi", label: "Hindi" },
      { value: "ta", label: "Tamil" },
    ]);
  });

  it("shows an unknown code as it is", () => {
    expect(languageOptions([tpl("x", { language: "fr" })])).toEqual([{ value: "fr", label: "fr" }]);
  });

  it("combines with the other filters", () => {
    expect(ids(filterTemplates(list, { ...NO_FILTERS, language: "ta", category: "MARKETING" }, usage))).toEqual(["b"]);
  });
});

describe("used-in filter", () => {
  it("Not used yet means no place at all (a finished campaign still counts as history)", () => {
    expect(ids(filterTemplates(list, { ...NO_FILTERS, usedIn: "NONE" }, usage))).toEqual(["d"]);
  });

  it("an area keeps only templates live there", () => {
    expect(ids(filterTemplates(list, { ...NO_FILTERS, usedIn: "follow_ups" }, usage))).toEqual(["a"]);
    expect(ids(filterTemplates(list, { ...NO_FILTERS, usedIn: "reach" }, usage))).toEqual([]);
  });

  it("lists only areas that are live somewhere", () => {
    expect(usedInOptions(usage)).toEqual([
      { value: "staff_alert", label: "Alert to staff" },
      { value: "follow_ups", label: "Follow-ups" },
    ]);
  });

  it("before the usage call answers, nothing is hidden by All", () => {
    expect(filterTemplates(list, NO_FILTERS, {})).toHaveLength(4);
  });

  it("search still works", () => {
    expect(ids(filterTemplates(list, { ...NO_FILTERS, search: "TPL_D" }, usage))).toEqual(["d"]);
  });
});

describe("used-in text", () => {
  it("joins live places, says so for finished ones, and for none", () => {
    expect(usedInText(usage.a)).toBe("Used in: Follow-ups");
    expect(usedInText(usage.b)).toBe("Was in Reach · ended");
    expect(usedInText(undefined)).toBe("Not used yet");
  });
});

describe("reasons on Rejected / Paused / Disabled", () => {
  it("rejected: Meta's reason in plain words and a way to fix it", () => {
    expect(statusNote(list[3])).toEqual({ text: "Meta: the wording or format isn't allowed", fixHref: "/dashboard/templates/d" });
  });

  it("an unknown reason is shown as Meta wrote it", () => {
    expect(plainRejection("Template contains a broken link")).toBe("Template contains a broken link");
  });

  it("paused: its reason, else the standard words", () => {
    expect(statusNote(tpl("p", { status: "PAUSED" }))?.text).toMatch(/Paused by Meta because people blocked or reported it/);
    expect(statusNote(tpl("p", { status: "PAUSED", rejection_reason: "SCAM" }))?.text).toBe("Meta: it looks like a scam");
  });

  it("disabled: make a new copy", () => {
    expect(statusNote(tpl("x", { status: "DISABLED" }))?.text).toBe("Meta turned it off after repeated pauses. Make a new copy.");
  });

  it("nothing for approved or pending", () => {
    expect(statusNote(tpl("a"))).toBeNull();
    expect(statusNote(tpl("a", { status: "PENDING" }))).toBeNull();
  });
});

describe("staff alert set as Marketing", () => {
  it("warns only for a Marketing template used as a staff alert", () => {
    expect(isStaffAlertMarketing(list[2], usage.c)).toBe(true);
    expect(isStaffAlertMarketing(tpl("c"), usage.c)).toBe(false); // Utility: fine
    expect(isStaffAlertMarketing(list[1], usage.b)).toBe(false);
  });
});

describe("Excel helpers", () => {
  it("download rows carry every column, used-in and reason", () => {
    const rows = downloadRows([list[3], tpl("a", { footer_text: "Aira" })], usage);
    expect(rows[0]).toEqual([
      "tpl_d", "Utility", "Tamil", "REJECTED", "Hello there", "", "", "Not used yet", "Meta: the wording or format isn't allowed",
    ]);
    expect(rows[1].slice(5, 9)).toEqual(["Aira", "", "Follow-ups", ""]);
  });

  it("type names and the counts line", () => {
    expect(typeName("MARKETING")).toBe("Marketing");
    expect(countsText({ ready: 4, need_fix: 2, exists: 1 })).toBe("4 ready · 2 need a fix · 1 already exists");
    expect(countsText({ ready: 0, need_fix: 0, exists: 0 })).toBe("Nothing found");
  });
});
