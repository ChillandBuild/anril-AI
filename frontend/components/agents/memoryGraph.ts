import type { CompanionMemoryFact } from "@/lib/api";

export const SECTION_LABEL: Record<CompanionMemoryFact["section"], string> = {
  profile: "Profile",
  people: "People",
  life: "Life",
  preferences: "Likes",
  threads: "Ongoing",
};

export type GraphNode = { id: string; kind: "person" | "section" | "fact"; label: string; x: number; y: number; closed?: boolean };
export type GraphEdge = { from: string; to: string };

const SIZE = 420;
const CENTER = SIZE / 2;

/**
 * Person in the middle, one node per section that has facts, facts fanned
 * around their section. Example: Karthik → Life → "lagnam Kumbham".
 */
export function layoutMemoryGraph(personLabel: string, facts: CompanionMemoryFact[]): { nodes: GraphNode[]; edges: GraphEdge[]; size: number } {
  const nodes: GraphNode[] = [{ id: "person", kind: "person", label: personLabel, x: CENTER, y: CENTER }];
  const edges: GraphEdge[] = [];
  const sections = (Object.keys(SECTION_LABEL) as CompanionMemoryFact["section"][]).filter((s) => facts.some((f) => f.section === s));
  sections.forEach((section, i) => {
    const angle = (2 * Math.PI * i) / sections.length - Math.PI / 2;
    const sx = CENTER + 95 * Math.cos(angle);
    const sy = CENTER + 95 * Math.sin(angle);
    const sid = `section:${section}`;
    nodes.push({ id: sid, kind: "section", label: SECTION_LABEL[section], x: sx, y: sy });
    edges.push({ from: "person", to: sid });
    const own = facts.filter((f) => f.section === section);
    const spread = Math.min(Math.PI / 1.5, (2 * Math.PI) / Math.max(sections.length, 1));
    own.forEach((fact, j) => {
      const offset = own.length === 1 ? 0 : (j / (own.length - 1) - 0.5) * spread;
      const fa = angle + offset;
      nodes.push({
        id: fact.id,
        kind: "fact",
        label: fact.text,
        x: sx + 80 * Math.cos(fa),
        y: sy + 80 * Math.sin(fa),
        closed: fact.status === "closed",
      });
      edges.push({ from: sid, to: fact.id });
    });
  });
  return { nodes, edges, size: SIZE };
}
