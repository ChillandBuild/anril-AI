import type { CSSProperties } from "react";

/**
 * Height of the strips the dashboard shell draws under the page header (components/nav/ModuleTabBar.tsx and
 * PageChips.tsx). A page that fills the screen (`h-[calc(100vh-...)]`) must subtract them, or its bottom edge
 * slips under the fold and the page scrolls twice.
 *
 * A page puts `style={moduleChromeStyle({ tabs: true })}` on its root and writes its height as
 * `h-[calc(100vh_-_5.5rem_-_var(--module-chrome))]`: one number to fix here if the bars ever change size.
 */
export const TAB_BAR_REM = 2.75;
export const CHIP_ROW_REM = 2.85;

export function moduleChromeRem(strips: { tabs?: boolean; chips?: boolean }): number {
  const total = (strips.tabs ? TAB_BAR_REM : 0) + (strips.chips ? CHIP_ROW_REM : 0);
  return Math.round(total * 100) / 100;
}

export function moduleChromeStyle(strips: { tabs?: boolean; chips?: boolean }): CSSProperties {
  return { ["--module-chrome" as string]: `${moduleChromeRem(strips)}rem` };
}
