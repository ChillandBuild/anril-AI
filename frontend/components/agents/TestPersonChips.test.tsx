import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NewPersonInput, TestPersonChips } from "@/components/agents/TestPersonChips";
import type { TestPerson } from "@/lib/api";

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

// The picker is one line until opened: "chatting as [● Vivek ⌄] ... Start over". The list of people,
// the bins and "+ New test customer" only exist while the menu is open.
describe("TestPersonChips (closed)", () => {
  const people: TestPerson[] = [
    { external_user_id: "you", name: "K Prem", is_you: true, profile_name: "K Prem" },
    { external_user_id: "u2", name: "Helo", is_you: false },
    { external_user_id: "u3", name: "Vivek", is_you: false },
  ];
  const html = renderToStaticMarkup(
    <TestPersonChips
      people={people}
      max={10}
      selectedId="u3"
      characterName="Jothidar AI"
      onPick={() => {}}
      onCreated={() => {}}
      onStartedOver={() => {}}
      onDeleted={() => {}}
    />,
  );

  it("shows only the chosen person, collapsed", () => {
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain(">Vivek</span>");
    expect(html).not.toContain("Helo");
    expect(html).not.toContain("New test customer");
    expect(html).not.toContain("Delete ");
  });

  it("calls You just You, even with a profile name saved", () => {
    const you = renderToStaticMarkup(
      <TestPersonChips people={people} max={10} selectedId="you" characterName="Jothidar AI" onPick={() => {}} onCreated={() => {}} onStartedOver={() => {}} onDeleted={() => {}} />,
    );
    expect(you).toContain(">You</span>");
    expect(you).not.toContain("K Prem");
  });

  it("keeps Start over on the same line", () => {
    expect(html).toContain("Start over");
  });
});
