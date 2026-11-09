"use client";
import { useEffect } from "react";

/**
 * The two products behind the Sales | Agents switch: Anril (shown as "Sales":
 * leads, chats, calls) and Anril Agents (AI characters). Each remembers the
 * last page you had open, so the switch takes you back there; clicking the
 * product you are in goes home.
 */
export type Product = "anril" | "agents";

/** What the switch calls each product. Example: an owner sees "Sales | Agents". */
export const PRODUCT_LABEL: Record<Product, string> = { anril: "Sales", agents: "Agents" };

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

const ANIM_MS = 450;
let animTimer: ReturnType<typeof setTimeout> | undefined;

function setProductAttr(product: Product, animate: boolean) {
  const root = document.documentElement;
  root.dataset.product = product;
  if (animate) root.dataset.productAnim = "";
  clearTimeout(animTimer);
  // Long enough for the next page to mount and fade in; then transitions stop
  // so ordinary navigation inside a product never animates the sidebar.
  animTimer = setTimeout(() => delete root.dataset.productAnim, animate ? 3000 : ANIM_MS);
}

/**
 * Called on a switch click, before navigating: the sidebar starts fading to
 * the target product's colours at once instead of waiting for the next page.
 */
export function startProductSwitch(target: Product) {
  setProductAttr(target, true);
}

/** Keeps data-product on <html> in step with the URL (back button, links). Mounted once in ClientLayout. */
export function useProductAttribute(pathname: string | null) {
  const product = productOf(pathname ?? "/dashboard");
  useEffect(() => {
    setProductAttr(product, false);
  }, [product]);
}
