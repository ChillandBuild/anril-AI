"use client";
import { useCallback, useEffect, useState } from "react";
import { FlaskConical, RefreshCw, Store } from "lucide-react";
import { toast } from "sonner";
import { API_URL, MarketplaceStatus, WabaTemplate, api, getAuthHeaders } from "@/lib/api";
import { SettingsSection } from "../SettingsSection";
import { CopyButton, timeAgo } from "./ui";

type ProviderId = "indiamart" | "justdial";

const PROVIDERS: { id: ProviderId; label: string; setup: string }[] = [
  {
    id: "indiamart",
    label: "IndiaMART",
    setup: "In your IndiaMART Seller panel, open Lead Manager → CRM integration (Push API) and paste this URL.",
  },
  {
    id: "justdial",
    label: "JustDial",
    setup: "Send this URL to your JustDial account manager and ask them to turn on lead push to it.",
  },
];

// A realistic enquiry in each provider's own shape, so "Send test enquiry"
// exercises the same parsing a real push goes through.
const SAMPLE_ENQUIRY: Record<ProviderId, Record<string, unknown>> = {
  indiamart: {
    CODE: 200,
    STATUS: "SUCCESS",
    RESPONSE: {
      UNIQUE_QUERY_ID: "TEST-ENQUIRY",
      SENDER_NAME: "Test Buyer",
      SENDER_MOBILE: "+91-9000000001",
      SENDER_CITY: "Chennai",
      QUERY_PRODUCT_NAME: "Test product",
      QUERY_MESSAGE: "This is a test enquiry from Anril settings.",
    },
  },
  justdial: {
    leadid: "TEST-ENQUIRY",
    name: "Test Buyer",
    mobile: "9000000002",
    category: "Test product",
    city: "Chennai",
  },
};

function ProviderCard({
  id,
  label,
  setup,
  canManage,
  status,
  onChanged,
}: {
  id: ProviderId;
  label: string;
  setup: string;
  canManage: boolean;
  status: MarketplaceStatus | null;
  onChanged: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/marketplace/${id}/token`, { headers: auth });
        if (!mounted) return;
        if (res.status === 403) setForbidden(true);
        else if (res.ok) setUrl((await res.json()).ingest_url);
      } catch {
        // Empty state (no URL yet) is the right default on a network blip.
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, [id]);

  async function handleGenerate() {
    setGenerating(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/marketplace/${id}/token`, {
        method: "POST",
        headers: { ...auth, "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error("Couldn't create the URL — try again");
      setUrl((await res.json()).ingest_url);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't create the URL");
    } finally {
      setGenerating(false);
    }
  }

  async function handleTest() {
    if (!url) return;
    setTesting(true);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(SAMPLE_ENQUIRY[id]),
      });
      if (!res.ok) throw new Error(`The test was rejected (HTTP ${res.status})`);
      toast.success(`Test enquiry received — "Test Buyer" is now in your ${label} leads`);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "The test enquiry didn't go through");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-3 rounded-2xl border border-border-subtle bg-surface-subtle p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-ink">{label}</p>
        {url && (
          <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-label text-[10px] font-bold uppercase text-emerald-700">
            URL ready
          </span>
        )}
      </div>

      {status && (
        <p className="font-body text-xs text-ink-secondary">
          {status.last_lead_at ? (
            <>
              Last enquiry <span className="font-semibold text-ink">{timeAgo(status.last_lead_at)}</span> ·{" "}
              {status.leads_this_month} this month
            </>
          ) : (
            "No enquiries received yet."
          )}
        </p>
      )}

      {loading ? (
        <div className="h-10 animate-pulse rounded-xl bg-border-subtle" />
      ) : forbidden ? (
        <p className="font-body text-xs text-ink-muted">Only admins can see this connection link.</p>
      ) : url ? (
        <>
          <p className="font-body text-xs text-ink-secondary">{setup}</p>
          <div className="flex items-center gap-2">
            <div className="flex-grow select-all break-all rounded-xl border border-border bg-white p-3 font-mono text-[11px] font-medium text-primary">
              {url}
            </div>
            <CopyButton text={url} />
          </div>
        </>
      ) : (
        <p className="font-body text-xs text-ink-muted">Create a link to connect {label}.</p>
      )}

      {canManage && !forbidden && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 font-label text-xs font-semibold text-ink-secondary transition-all hover:border-primary/40 hover:text-primary disabled:opacity-40"
          >
            <RefreshCw size={12} className={generating ? "animate-spin" : ""} />
            {url ? "New link" : "Create link"}
          </button>
          {url && (
            <button
              type="button"
              onClick={handleTest}
              disabled={testing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 font-label text-xs font-semibold text-ink-secondary transition-all hover:border-primary/40 hover:text-primary disabled:opacity-40"
            >
              <FlaskConical size={12} />
              {testing ? "Sending…" : "Send test enquiry"}
            </button>
          )}
        </div>
      )}
      {url && canManage && (
        <p className="font-body text-[10px] text-ink-muted">
          A new link stops the old one working straight away — update {label} with it.
        </p>
      )}
    </div>
  );
}

function WelcomeTemplatePicker({ canManage }: { canManage: boolean }) {
  const [templates, setTemplates] = useState<WabaTemplate[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<string>("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([api.templates.list(), api.marketplace.getWelcomeTemplate()])
      .then(([all, current]) => {
        setTemplates(all.filter((t) => (t.status || "").toUpperCase() === "APPROVED"));
        setSelected(current.template_id ?? "");
      })
      .catch(() => toast.error("Couldn't load your WhatsApp templates"))
      .finally(() => setLoaded(true));
  }, []);

  async function save(templateId: string) {
    setSelected(templateId);
    setSaving(true);
    try {
      await api.marketplace.setWelcomeTemplate(templateId || null);
      toast.success(templateId ? "Welcome message saved" : "Welcome message turned off");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save the welcome message");
    } finally {
      setSaving(false);
    }
  }

  const preview = templates.find((t) => t.id === selected)?.body_text;

  return (
    <div className="space-y-2 rounded-2xl border border-primary/15 bg-primary/[0.03] p-5">
      <p className="text-sm font-semibold text-ink">First WhatsApp message</p>
      <p className="font-body text-xs text-ink-secondary">
        Buyers usually message several sellers at once — the first reply wins. Pick an approved template and Anril
        sends it within seconds of every new enquiry. {"{{1}}"} becomes the buyer&apos;s first name, {"{{2}}"} the
        product they asked about.
      </p>
      <select
        value={selected}
        disabled={!canManage || saving || !loaded}
        onChange={(e) => save(e.target.value)}
        className="w-full rounded-xl border border-border bg-white px-3 py-2 font-body text-sm text-ink disabled:opacity-60"
      >
        <option value="">Don&apos;t send a message</option>
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
      {preview && <p className="rounded-xl bg-white p-3 font-body text-xs text-ink-secondary">{preview}</p>}
      {loaded && templates.length === 0 && (
        <p className="font-body text-[11px] text-ink-muted">No approved templates yet — create one under Templates.</p>
      )}
    </div>
  );
}

export default function MarketplaceLeadsSection({ canManage = true }: { canManage?: boolean }) {
  const [status, setStatus] = useState<Record<ProviderId, MarketplaceStatus> | null>(null);

  const loadStatus = useCallback(() => {
    api.marketplace.status().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const connectedCount = status ? PROVIDERS.filter((p) => status[p.id]?.connected).length : 0;

  return (
    <SettingsSection
      id="marketplace-leads"
      icon={Store}
      accent="sky"
      title="IndiaMART & JustDial"
      description="Buyers find you on these directories and send an enquiry. Connect them and every enquiry lands here as a lead in seconds — with what they asked for — gets your WhatsApp message, and goes to the top of the call list."
      status={status ? { label: connectedCount ? `${connectedCount} connected` : "Not connected", tone: connectedCount ? "on" : "warn" } : undefined}
    >
      <div className="space-y-4">
        <WelcomeTemplatePicker canManage={canManage} />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {PROVIDERS.map((p) => (
            <ProviderCard
              key={p.id}
              {...p}
              canManage={canManage}
              status={status?.[p.id] ?? null}
              onChanged={loadStatus}
            />
          ))}
        </div>
      </div>
    </SettingsSection>
  );
}
