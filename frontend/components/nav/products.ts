"use client";
import { useEffect } from "react";

/**
 * The two products on the product rail: Anril (WhatsApp sales) and Anril
 * Agents (AI characters). Each remembers the last page you had open, so the
 * rail takes you back there; clicking the product you are in goes home.
 */
export type Product = "anril" | "agents";

export const PRODUCT_HOME: Record<Product, string> = {
  anril: "/dashboard",
  agents: "/dashboard/agents",
};

const STORAGE_KEY = "anril.product-last-path";

export function productOf(pathname: string): Product {
  const path = pathname.split("?")[0];
  return path === "/dashboard/agents" || path.startsWith("/dashboard/agents/") ? "agents" : "anril";
}

/** Where a click on `target` goes from `pathname`, given the remembered pages. */
export function productHref(
  target: Product,
  pathname: string,
  last: Partial<Record<Product, string>>,
): string {
  if (productOf(pathname) === target) return PRODUCT_HOME[target];
  const remembered = last[target];
  // Only a dashboard path of the same product: never an outside URL.
  if (remembered && remembered.startsWith("/dashboard") && productOf(remembered) === target) {
    return remembered;
  }
  return PRODUCT_HOME[target];
}

/** Who sees Anril Agents: the owner, or a role with companions.manage. */
export function canSeeAgents(role: string | null, permissions: readonly string[]): boolean {
  return role === "owner" || permissions.includes("companions.manage");
}

export function readLastPaths(): Partial<Record<Product, string>> {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Partial<Record<Product, string>>) : {};
  } catch {
    return {};
  }
}

/** Remembers the current page under its product. Mounted once in ClientLayout. */
export function useRememberProductPage(pathname: string | null) {
  useEffect(() => {
    if (!pathname) return;
    try {
      const last = readLastPaths();
      last[productOf(pathname)] = pathname + window.location.search;
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(last));
    } catch {
      // Private mode or blocked storage: the rail just goes home.
    }
  }, [pathname]);
}
