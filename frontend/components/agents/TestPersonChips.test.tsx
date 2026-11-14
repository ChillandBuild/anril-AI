import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NewPersonInput } from "@/components/agents/TestPersonChips";

// The chips sit inside the message box's <form>. A <form> inside a <form> makes Add reload the page
// (the browser submits it itself: "?n=Prem"), so the name box must be a plain row with a click button.
describe("NewPersonInput", () => {
  const html = renderToStaticMarkup(
    <form>
      <NewPersonInput name="Prem" busy={false} onName={() => {}} onAdd={() => {}} onCancel={() => {}} />
    </form>,
  );

  it("adds no form of its own inside the message box", () => {
    expect(html.match(/<form/g)).toHaveLength(1);
  });

  it("makes Add a plain button, not a submit", () => {
    expect(html).toMatch(/<button type="button"[^>]*>Add<\/button>/);
    expect(html).not.toContain('type="submit"');
  });
});
