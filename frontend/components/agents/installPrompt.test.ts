import { describe, expect, it } from "vitest";
import { appPrompt, installPrompt } from "./installPrompt";

const info = {
  companion_id: "c1",
  status: "live" as const,
  widget_script_url: "https://www.anrilaitech.com/companion-widget.js",
  api_base: "https://api.example",
  has_active_key: true,
  snippets: {
    html: "<script src=x></script>", python: "def companion_signature(): ...", node: "function companionSignature() {}",
    curl: "curl x", chat_python: "def ask_anril(user_id, message): ...", chat_node: "async function askAnril() {}",
    chat_php: "<?php function ask_anril() {}",
  },
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

describe("appPrompt", () => {
  const text = appPrompt(info, "Maya");

  it("fills in this character's id and the API address", () => {
    expect(text).toContain('"Maya"');
    expect(text).toContain("`c1`");
    expect(text).toContain("https://api.example/api/v1/companion/chat");
    expect(text).toContain("https://api.example/api/v1/companion/forget");
    expect(text).toContain(info.snippets.chat_python);
  });

  it("covers profiles, the data, the reply and the errors", () => {
    for (const word of ["profile_id", "ALWAYS send it", "app_data", "reply_format", "tag", "rate_limited", "need_details"]) {
      expect(text).toContain(word);
    }
  });

  it("is not about the website widget and holds no key", () => {
    expect(text).not.toContain(info.snippets.html);
    expect(text).not.toContain("/widget/");
    expect(text).not.toMatch(/acs_live_[A-Za-z0-9]{8,}/);
    expect(text).toContain("ANRIL_COMPANION_KEY");
  });
});
