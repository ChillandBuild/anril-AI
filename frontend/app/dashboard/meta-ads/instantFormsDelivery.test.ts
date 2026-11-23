import { describe, expect, it } from "vitest";
import { deliveryLook, formTemplateText, helloLook } from "./instantFormsDelivery";

describe("deliveryLook", () => {
  it("shows the real receipt", () => {
    expect(deliveryLook("read", null, "sent")?.label).toBe("Read");
    expect(deliveryLook("delivered", null, "sent")?.label).toBe("Delivered");
    expect(deliveryLook("failed", null, "sent")?.label).toBe("Not delivered");
  });

  it("says no WhatsApp, and that the person went to calling", () => {
    expect(deliveryLook("no_whatsapp", "2026-11-23T10:00:00Z", "failed")?.label).toBe("No WhatsApp, sent to calling");
    expect(deliveryLook("no_whatsapp", null, "failed")?.label).toBe("No WhatsApp");
  });

  it("shows nothing before a receipt arrives", () => {
    expect(deliveryLook(null, null, "sent")).toBeNull();
    expect(deliveryLook(undefined, undefined, "no_template")).toBeNull();
  });
});

describe("helloLook", () => {
  it("maps each state to words and a button", () => {
    expect(helloLook("none")).toMatchObject({ label: "Not set up", button: "Set up" });
    expect(helloLook(undefined)).toMatchObject({ label: "Not set up", button: "Set up" });
    expect(helloLook("waiting")).toMatchObject({ label: "Waiting for Meta", button: null });
    expect(helloLook("approved")).toMatchObject({ label: "Approved", button: null });
    expect(helloLook("rejected").button).toBe("Send again");
  });
});

describe("formTemplateText", () => {
  it("prefers the form's own template", () => {
    expect(formTemplateText({ template_name: "welcome", uses_hello: true }, "approved")).toEqual({ kind: "own", text: "welcome" });
  });

  it("says auto when the hello will be used, off when switched off", () => {
    expect(formTemplateText({ template_name: null, uses_hello: true, auto_hello: true }, "approved").kind).toBe("auto");
    expect(formTemplateText({ template_name: null, auto_hello: false }, "approved").kind).toBe("off");
    expect(formTemplateText({ template_name: null, auto_hello: true }, "waiting").kind).toBe("auto_waiting");
    expect(formTemplateText({ template_name: null, auto_hello: true }, "none").kind).toBe("none");
  });
});
