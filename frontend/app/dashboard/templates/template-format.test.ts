import { describe, expect, it } from "vitest";
import { formatSegments, insertAt, toggleWrap } from "./template-format";
import { CUSTOMER_DETAILS, nextVarNumber, variableChip } from "./template-details";

describe("insertAt", () => {
  it("puts text at the cursor and moves the cursor after it", () => {
    const r = insertAt("Hi !", 3, 3, "🙏", 100)!;
    expect(r.value).toBe("Hi 🙏!");
    expect(r.selStart).toBe(5);
  });
  it("replaces a selection", () => {
    expect(insertAt("Hi NAME", 3, 7, "{{1}}", 100)!.value).toBe("Hi {{1}}");
  });
  it("refuses to go over the limit", () => {
    expect(insertAt("abcd", 4, 4, "{{1}}", 8)).toBeNull();
  });
});

describe("toggleWrap", () => {
  it("wraps the selection", () => {
    const r = toggleWrap("Sale today", 0, 4, "*", 100)!;
    expect(r.value).toBe("*Sale* today");
    expect([r.selStart, r.selEnd]).toEqual([1, 5]);
  });
  it("keeps edge spaces outside the marker", () => {
    expect(toggleWrap("a Sale b", 1, 7, "_", 100)!.value).toBe("a _Sale_ b");
  });
  it("drops a pair with the cursor between when nothing is selected", () => {
    const r = toggleWrap("ab", 1, 1, "*", 100)!;
    expect(r.value).toBe("a**b");
    expect(r.selStart).toBe(2);
  });
  it("takes the marker off when the selection includes it", () => {
    expect(toggleWrap("*Sale* today", 0, 6, "*", 100)!.value).toBe("Sale today");
  });
  it("takes the marker off when it sits just outside the selection", () => {
    expect(toggleWrap("*Sale* today", 1, 5, "*", 100)!.value).toBe("Sale today");
  });
  it("refuses to go over the limit", () => {
    expect(toggleWrap("abcd", 0, 4, "*", 5)).toBeNull();
  });
});

describe("formatSegments", () => {
  it("reads bold and italic", () => {
    expect(formatSegments("a *b* and _c_ d")).toEqual([
      { kind: "text", text: "a " },
      { kind: "bold", text: "b" },
      { kind: "text", text: " and " },
      { kind: "italic", text: "c" },
      { kind: "text", text: " d" },
    ]);
  });
  it("keeps a variable inside bold", () => {
    expect(formatSegments("*Hi {{1}}*")).toEqual([{ kind: "bold", text: "Hi {{1}}" }]);
  });
  it("ignores spaced markers and snake_case words", () => {
    expect(formatSegments("* hi * and my_var_name")).toEqual([{ kind: "text", text: "* hi * and my_var_name" }]);
  });
  it("does not run across a new line", () => {
    expect(formatSegments("*a\nb*")).toEqual([{ kind: "text", text: "*a\nb*" }]);
  });
});

describe("customer details", () => {
  it("numbers the next variable and labels it", () => {
    expect(nextVarNumber([])).toBe(1);
    expect(nextVarNumber([1, 3])).toBe(4);
    expect(variableChip(2, { 2: "Customer name" })).toBe("{{2}} = Customer name");
    expect(variableChip(1, {})).toBe("{{1}}");
  });
  it("gives every detail an example, because Meta needs one", () => {
    for (const d of CUSTOMER_DETAILS) expect(d.sample.trim()).not.toBe("");
  });
});
