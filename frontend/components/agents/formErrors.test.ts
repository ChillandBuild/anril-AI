import { describe, expect, it } from "vitest";
import { fieldErrors, saveErrorMessage } from "./formErrors";

describe("fieldErrors", () => {
  it("maps a 422 loc to its field, list items to the list field", () => {
    const detail = [
      { loc: ["body", "name"], msg: "String should have at most 80 characters" },
      { loc: ["body", "sample_lines", 2], msg: "Value error, too long" },
    ];
    expect(fieldErrors(detail)).toEqual({
      name: "String should have at most 80 characters",
      sample_lines: "too long",
    });
  });

  it("keeps the first message per field and ignores junk", () => {
    const detail = [{ loc: ["body", "goals", 0], msg: "a" }, { loc: ["body", "goals", 1], msg: "b" }, "x", null, { msg: "no loc" }];
    expect(fieldErrors(detail)).toEqual({ goals: "a" });
  });

  it("returns nothing for a string detail", () => {
    expect(fieldErrors("Not found")).toEqual({});
  });
});

describe("saveErrorMessage", () => {
  it("409 means the name is taken", () => {
    const err = Object.assign(new Error("You already have a character with that name"), { status: 409 });
    expect(saveErrorMessage(err)).toEqual({ fields: { name: "Name already used" }, message: "" });
  });

  it("422 with fields points at them", () => {
    const err = Object.assign(new Error("x"), { status: 422, detail: [{ loc: ["body", "role"], msg: "too long" }] });
    expect(saveErrorMessage(err)).toEqual({ fields: { role: "too long" }, message: "Fix the highlighted fields." });
  });

  it("anything else shows the server message", () => {
    const err = Object.assign(new Error("That books tag isn't one of your tags"), { status: 422, detail: "That books tag isn't one of your tags" });
    expect(saveErrorMessage(err)).toEqual({ fields: {}, message: "That books tag isn't one of your tags" });
  });
});
