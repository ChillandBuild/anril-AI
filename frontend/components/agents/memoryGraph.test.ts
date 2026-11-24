import { describe, expect, it } from "vitest";
import type { CompanionMemoryFact } from "@/lib/api";
import { FACT_CHAR_W, MAX_FACT_CHARS, layoutMemoryGraph, type GraphNode } from "./memoryGraph";

const fact = (id: string, section: CompanionMemoryFact["section"], text: string): CompanionMemoryFact => ({
  id, section, text, valid_from: null, valid_to: null, status: "active", learned_by: "Maya",
});

describe("layoutMemoryGraph", () => {
  it("links person → section → fact, only for sections with facts", () => {
    const { nodes, edges } = layoutMemoryGraph("Karthik", [fact("f1", "life", "lagnam Kumbham"), fact("f2", "life", "works at Infosys"), fact("f3", "people", "sister Meena")]);
    expect(nodes.filter((n) => n.kind === "section").map((n) => n.label).sort()).toEqual(["Life", "People"]);
    expect(edges).toContainEqual({ from: "person", to: "section:life" });
    expect(edges).toContainEqual({ from: "section:life", to: "f2" });
    expect(nodes).toHaveLength(1 + 2 + 3);
  });

  // A fact label's box on the canvas, as the renderer draws it (9px text, anchored at lx).
  const labelBox = (n: GraphNode) => {
    const w = n.text.length * FACT_CHAR_W;
    const x0 = n.anchor === "end" ? n.lx - w : n.anchor === "middle" ? n.lx - w / 2 : n.lx;
    return { x0, x1: x0 + w, y0: n.ly - 9, y1: n.ly + 2 };
  };
  const overlaps = (a: ReturnType<typeof labelBox>, b: ReturnType<typeof labelBox>) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  const sections = ["profile", "people", "life", "preferences", "threads"] as const;
  const long = "டிசம்பர் 2026-க்குள் வெளிநாட்டு வேலைக்கு போக திட்டம் இருக்கிறது";

  it("never overlaps fact labels (Vivek: four Ongoing facts that used to collide)", () => {
    const vivek = [
      fact("p1", "profile", "பெயர் கார்த்திக்"),
      fact("t1", "threads", long),
      fact("t2", "threads", "வெளிநாட்டு வேலை தேடுகிறார்"),
      fact("t3", "threads", "அடுத்த வாரம் இன்டர்வியூ இருக்கிறது"),
      fact("t4", "threads", "பைக் வாங்குவதா என்று யோசிக்கிறார்"),
    ];
    const heavy = Array.from({ length: 30 }, (_, i) => fact(`f${i}`, sections[i % 5], `${long} ${i}`));
    for (const set of [vivek, heavy]) {
      const labels = layoutMemoryGraph("Vivek", set).nodes.filter((n) => n.kind === "fact").map(labelBox);
      for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) expect(overlaps(labels[i], labels[j]), `labels ${i} and ${j}`).toBe(false);
    }
  });

  it("puts sections on both sides and runs labels away from the centre", () => {
    const { nodes } = layoutMemoryGraph("Karthik", [fact("a", "profile", "x"), fact("b", "threads", "y")]);
    const person = nodes.find((n) => n.kind === "person")!;
    const [a, b] = ["a", "b"].map((id) => nodes.find((n) => n.id === id)!);
    expect(Math.sign(a.x - person.x)).toBe(-Math.sign(b.x - person.x));
    for (const f of [a, b]) expect(f.anchor).toBe(f.x > person.x ? "start" : "end");
  });

  it("cuts long fact text on the canvas but keeps the full text for the tooltip", () => {
    const n = layoutMemoryGraph("Karthik", [fact("a", "life", long)]).nodes.find((x) => x.id === "a")!;
    expect(n.text.length).toBe(MAX_FACT_CHARS);
    expect(n.text.endsWith("…")).toBe(true);
    expect(n.label).toBe(long);
  });

  it("keeps every node and label inside the canvas", () => {
    const many = Array.from({ length: 12 }, (_, i) => fact(`f${i}`, sections[i % 5], i % 2 ? long : "x"));
    for (const set of [many, many.slice(0, 1)]) {
      const { nodes, width, height } = layoutMemoryGraph("Karthik", set);
      for (const n of nodes) {
        expect(n.x).toBeGreaterThanOrEqual(0);
        expect(n.x).toBeLessThanOrEqual(width);
        expect(n.y).toBeGreaterThanOrEqual(0);
        expect(n.ly).toBeLessThanOrEqual(height);
        if (n.kind === "fact") {
          const box = labelBox(n);
          expect(box.x0).toBeGreaterThanOrEqual(0);
          expect(box.x1).toBeLessThanOrEqual(width);
          expect(box.y0).toBeGreaterThanOrEqual(0);
        }
      }
    }
  });
});
