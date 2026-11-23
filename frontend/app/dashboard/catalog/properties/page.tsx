"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Plus, Search } from "lucide-react";
import { propertiesApi, kindLine, priceRangeText, unitsText, type Property } from "@/lib/propertiesApi";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import { CatalogueTabs } from "../CatalogueTabs";

/* 🏘 Properties (real estate): one card per property. A property is a catalogue item with real-estate details;
 * site visits are Bookings. Backend: routes/properties.py. */

function Card({ p }: { p: Property }) {
  const price = priceRangeText(p.price_min_paise, p.price_max_paise);
  const sold = p.units_left === 0;
  return (
    <Link
      href={`/dashboard/catalog/properties/${p.id}`}
      className="block rounded-card border border-border bg-white p-4 shadow-sm transition-colors hover:border-primary/40"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{p.name}</p>
          <p className="truncate text-xs text-ink-muted">{[p.project, kindLine(p), p.size_text].filter(Boolean).join(" · ")}</p>
        </div>
        {!p.ai_on && <span className="shrink-0 rounded-full bg-surface-mid px-2 py-0.5 text-xs font-semibold text-ink-muted">AI off</span>}
      </div>
      {price && <p className="mt-2 text-sm font-semibold text-ink">{price}</p>}
      <p className={sold ? "mt-1 text-xs font-semibold text-red-700" : "mt-1 text-xs text-ink-muted"}>{unitsText(p.units_left, p.units_total)}</p>
      {p.rera_no && <p className="mt-1 text-xs text-ink-muted">RERA {p.rera_no}</p>}
    </Link>
  );
}

export default function PropertiesPage() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("catalog.manage");
  const [query, setQuery] = useState("");
  const { data, error, isLoading } = useSWR(["properties", query], () => propertiesApi.list(query.trim() || undefined));

  return (
    <div className="space-y-4">
      <CatalogueTabs />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-ink">🏘 Properties</h1>
          <p className="text-sm text-ink-muted">The flats, villas and plots you sell. The AI agent asks budget, BHK, area and loan need, then offers a site visit.</p>
        </div>
        {canManage && (
          <Link href="/dashboard/catalog/properties/new" className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white">
            <Plus className="h-4 w-4" aria-hidden /> Add property
          </Link>
        )}
      </div>

      <label className="relative block max-w-sm">
        <span className="sr-only">Search properties</span>
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name or project"
          className="w-full rounded-lg border border-border bg-white py-2 pl-9 pr-3 text-sm text-ink focus:border-primary focus:outline-none"
        />
      </label>

      {error && <p role="alert" className="text-sm text-red-700">Could not load your properties. Please try again.</p>}
      {isLoading && <div className="h-32 animate-pulse rounded-card bg-surface-low" />}
      {data && data.length === 0 && !error && (
        <div className="rounded-card border border-dashed border-border bg-white p-8 text-center text-sm text-ink-muted">
          {query ? "No property matches that search." : "No properties yet. Add your first one and the AI agent can start talking about it."}
        </div>
      )}
      {data && data.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((p) => <Card key={p.id} p={p} />)}
        </div>
      )}

      <p className="text-xs text-ink-muted">
        Coming later: when someone liked a property but is still thinking, the AI agent follows up with loan help after 2 days.
      </p>
    </div>
  );
}
