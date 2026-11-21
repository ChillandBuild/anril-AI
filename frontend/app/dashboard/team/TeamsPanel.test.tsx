import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import TeamsPanel from "./TeamsPanel";
import type { CallTeamsResponse } from "@/lib/api";

const data: CallTeamsResponse = {
  teams_ready: true,
  can_manage: true,
  data: [
    {
      id: "t1",
      name: "Team A",
      members: [{ caller_id: "c1", name: "Anitha", user_id: "u1" }],
      leaders: [{ user_id: "u9", name: "Ravi" }],
    },
  ],
  unteamed: [{ caller_id: "c2", name: "Meena", user_id: "u2" }],
};

describe("TeamsPanel", () => {
  it("shows each team with its leaders and telecallers, plus the add button", () => {
    const html = renderToStaticMarkup(<TeamsPanel data={data} onChanged={() => undefined} />);
    expect(html).toContain("Team A");
    expect(html).toContain("Ravi");
    expect(html).toContain("Anitha");
    expect(html).toContain("Teams");
    expect(html).not.toContain("not switched on");
  });

  it("says so when the teams update is not switched on", () => {
    const html = renderToStaticMarkup(
      <TeamsPanel data={{ ...data, teams_ready: false, data: [] }} onChanged={() => undefined} />,
    );
    expect(html).toContain("not switched on yet");
  });
});
