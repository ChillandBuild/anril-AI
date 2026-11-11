import { describe, expect, it } from "vitest";
import { installPrompt } from "./installPrompt";

const info = {
  companion_id: "c1",
  status: "live" as const,
  widget_script_url: "https://www.anrilaitech.com/companion-widget.js",
  api_base: "https://api.example",
  has_active_key: true,
  snippets: { html: "<script src=x></script>", python: "def companion_signature(): ...", node: "function companionSignature() {}", curl: "curl x" },
};

describe("installPrompt", () => {
  it("names the character and carries every snippet the site needs", () => {
    const text = installPrompt(info, "Maya");
    expect(text).toContain('"Maya"');
    expect(text).toContain(info.snippets.html);
    expect(text).toContain(info.snippets.python);
    expect(text).toContain(info.snippets.node);
    expect(text).toContain("ANRIL_COMPANION_KEY");
  });

  it("never contains a key", () => {
    expect(installPrompt(info, "Maya")).not.toMatch(/acs_live_[A-Za-z0-9]{8,}/);
  });
});
