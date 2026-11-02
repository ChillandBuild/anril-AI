"use client";
import { createContext, useContext, ReactNode } from "react";

export type SubscriptionStatus = "active" | "none" | "pending_approval";

interface SubscriptionContextType {
  status: SubscriptionStatus;
  /** feature_key of every purchased subscription item. */
  purchasedFeatures: string[];
}

// ClientLayout fetches /subscriptions/me once, before the dashboard renders, and
// hands the answer down here. Nav pieces read it instead of re-fetching, so they
// paint with the page instead of showing an empty shell while a second call runs.
// The default fails open, matching the fetch's own error handling.
const SubscriptionContext = createContext<SubscriptionContextType>({
  status: "active",
  purchasedFeatures: [],
});

export function SubscriptionProvider({ value, children }: { value: SubscriptionContextType; children: ReactNode }) {
  return <SubscriptionContext.Provider value={value}>{children}</SubscriptionContext.Provider>;
}

export const useSubscription = () => useContext(SubscriptionContext);
