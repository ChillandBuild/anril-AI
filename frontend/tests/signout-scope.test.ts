/**
 * Every supabase.auth.signOut() must name its scope.
 *
 * The default scope is "global": it deletes ALL of that user's sessions, including the one the
 * Claude connectors (Anril Admin and Anril AI) hold. The connector then cannot renew its token and
 * shows "Sign-in expired". So a sign-out must say "local" (this browser only) or "others" (a
 * deliberate security sign-out, e.g. after a password change). Never "global" and never the default.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const SKIP = new Set(["node_modules", ".next", "tests", "public"]);

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full));
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

describe("supabase signOut scope", () => {
  it("every signOut() call names scope local or others", () => {
    const bad: string[] = [];
    for (const file of sourceFiles(ROOT)) {
      const text = readFileSync(file, "utf8");
      for (const match of Array.from(text.matchAll(/\.signOut\(([^)]*)\)/g))) {
        if (!/scope:\s*["'](local|others)["']/.test(match[1])) {
          const line = text.slice(0, match.index).split("\n").length;
          bad.push(`${path.relative(ROOT, file)}:${line}  signOut(${match[1].trim()})`);
        }
      }
    }
    expect(bad, `signOut without scope "local" or "others":\n${bad.join("\n")}`).toEqual([]);
  });
});
