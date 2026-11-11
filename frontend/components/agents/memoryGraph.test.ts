import { describe, expect, it } from "vitest";
import type { CompanionMemoryFact } from "@/lib/api";
import { layoutMemoryGraph } from "./memoryGraph";

const fact = (id: string, section: CompanionMemoryFact["section"], text: string): CompanionMemoryFact => ({
  id, section, text, valid_from: null, valid_to: null, status: "active", learned_by: "Maya",
});

describe("layoutMemoryGraph", () => {
  it("links person → section → fact, only for sections with facts", () => {
    const { nodes, edges } = layoutMemoryGraph("Karthik", [fact("f1", "life", "lagnam Kumbham"), fact("f2", "life", "works at Infosys"), fact("f3", "people", "sister Meena")]);
    expect(nodes.filter((n) => n.kind === "section").map((n) => n.label)).toEqual(["People", "Life"]);
    expect(edges).toContainEqual({ from: "person", to: "section:life" });
    expect(edges).toContainEqual({ from: "section:life", to: "f2" });
    expect(nodes).toHaveLength(1 + 2 + 3);
  });

  it("keeps every node inside the canvas", () => {
    const many = Array.from({ length: 12 }, (_, i) => fact(`f${i}`, (["profile", "people", "life", "preferences", "threads"] as const)[i % 5], "x"));
    const { nodes, size } = layoutMemoryGraph("Karthik", many);
    for (const n of nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(size);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeLessThanOrEqual(size);
    }
  });
});
