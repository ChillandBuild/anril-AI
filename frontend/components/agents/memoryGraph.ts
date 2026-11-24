import type { CompanionMemoryFact } from "@/lib/api";

export const SECTION_LABEL: Record<CompanionMemoryFact["section"], string> = {
  profile: "Profile",
  people: "People",
  life: "Life",
  preferences: "Likes",
  threads: "Ongoing",
};

export type LabelAnchor = "start" | "middle" | "end";
export type GraphNode = {
  id: string;
  kind: "person" | "section" | "fact";
  /** Full text, shown in the hover tooltip. */
  label: string;
  /** What is drawn on the canvas (fact text is cut to MAX_FACT_CHARS). */
  text: string;
  x: number;
  y: number;
  /** Where the label is drawn and which way it runs from there. */
  lx: number;
  ly: number;
  anchor: LabelAnchor;
  closed?: boolean;
};
export type GraphEdge = { from: string; to: string };
export type MemoryGraphLayout = { nodes: GraphNode[]; edges: GraphEdge[]; width: number; height: number };

/** Each fact gets its own row, so labels on one side can never overlap. */
export const FACT_ROW = 22;
export const MAX_FACT_CHARS = 34;
/** Rough width of one character at the 9px fact font (Tamil runs wider than Latin, so err high). */
export const FACT_CHAR_W = 6;
const SECTION_X = 110;
const FACT_X = 175;
const LABEL_GAP = 9;
const GROUP_GAP = 14;
const MIN_GROUP = 58; // section circle + its label underneath
const PAD = 16;

const cut = (text: string) => (text.length > MAX_FACT_CHARS ? `${text.slice(0, MAX_FACT_CHARS - 1)}…` : text);

/**
 * Mind map: person in the middle, sections split left and right, and each
 * section's facts listed one per row beside it. Example: Vivek → Ongoing →
 * four facts stacked 22px apart on the left, Profile → "பெயர் கார்த்திக்" on the right.
 * Coordinates are shifted so the whole map sits inside 0..width × 0..height.
 */
export function layoutMemoryGraph(personLabel: string, facts: CompanionMemoryFact[]): MemoryGraphLayout {
  const sections = (Object.keys(SECTION_LABEL) as CompanionMemoryFact["section"][])
    .map((section) => ({ section, own: facts.filter((f) => f.section === section) }))
    .filter((g) => g.own.length > 0);

  // Balance the two sides by height; ties go right so a single section reads left-to-right.
  const sides: Record<"left" | "right", typeof sections> = { left: [], right: [] };
  const groupHeight = (n: number) => Math.max(MIN_GROUP, n * FACT_ROW);
  const sideHeight = (list: typeof sections) =>
    list.reduce((sum, g) => sum + groupHeight(g.own.length), 0) + Math.max(0, list.length - 1) * GROUP_GAP;
  for (const g of sections) {
    (sideHeight(sides.right) <= sideHeight(sides.left) ? sides.right : sides.left).push(g);
  }
  const height = Math.max(sideHeight(sides.left), sideHeight(sides.right), MIN_GROUP);

  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const person: GraphNode = { id: "person", kind: "person", label: personLabel, text: personLabel, x: 0, y: height / 2, lx: 0, ly: height / 2 + 36, anchor: "middle" };
  nodes.push(person);

  for (const side of ["left", "right"] as const) {
    const dir = side === "left" ? -1 : 1;
    let top = (height - sideHeight(sides[side])) / 2;
    for (const { section, own } of sides[side]) {
      const gh = groupHeight(own.length);
      const sid = `section:${section}`;
      const sy = top + gh / 2;
      nodes.push({ id: sid, kind: "section", label: SECTION_LABEL[section], text: SECTION_LABEL[section], x: dir * SECTION_X, y: sy, lx: dir * SECTION_X, ly: sy + 28, anchor: "middle" });
      edges.push({ from: "person", to: sid });
      const rowsTop = sy - (own.length * FACT_ROW) / 2;
      own.forEach((fact, j) => {
        const fy = rowsTop + FACT_ROW * (j + 0.5);
        nodes.push({
          id: fact.id,
          kind: "fact",
          label: fact.text,
          text: cut(fact.text),
          x: dir * FACT_X,
          y: fy,
          lx: dir * (FACT_X + LABEL_GAP),
          ly: fy + 3, // baseline nudge so 9px text sits centred on the dot
          anchor: side === "left" ? "end" : "start",
          closed: fact.status === "closed",
        });
        edges.push({ from: sid, to: fact.id });
      });
      top += gh + GROUP_GAP;
    }
  }

  // Shift into positive space, leaving room for the widest label on each side.
  const labelWidth = (n: GraphNode) => n.text.length * FACT_CHAR_W;
  const reach = (dir: -1 | 1) =>
    Math.max(SECTION_X + 40, ...nodes.filter((n) => n.kind === "fact" && Math.sign(n.x) === dir).map((n) => Math.abs(n.lx) + labelWidth(n)));
  const left = reach(-1);
  const right = reach(1);
  for (const n of nodes) {
    n.x += left + PAD;
    n.lx += left + PAD;
    n.y += PAD;
    n.ly += PAD;
  }
  return { nodes, edges, width: left + right + 2 * PAD, height: Math.max(height, height / 2 + 44) + 2 * PAD };
}
