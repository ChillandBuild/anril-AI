import { describe, expect, it } from "vitest";
import { resolveTelecallingAccess } from "./telecalling-access";

describe("resolveTelecallingAccess", () => {
  it("owner can dial and view", () => {
    expect(resolveTelecallingAccess("owner", [])).toEqual({ canDial: true, canViewTelecalling: true });
  });
  it("caller with the dialer permission can dial and view", () => {
    expect(resolveTelecallingAccess("caller", ["telecalling.dialer"])).toEqual({ canDial: true, canViewTelecalling: true });
  });
  it("view-only permissions can see but not dial", () => {
    for (const p of ["telecalling.dialer.view", "leads.view", "team.view"]) {
      expect(resolveTelecallingAccess("caller", [p])).toEqual({ canDial: false, canViewTelecalling: true });
    }
  });
  it("no relevant permission sees nothing", () => {
    expect(resolveTelecallingAccess("caller", ["notes.view"])).toEqual({ canDial: false, canViewTelecalling: false });
    expect(resolveTelecallingAccess(null, [])).toEqual({ canDial: false, canViewTelecalling: false });
  });
});
