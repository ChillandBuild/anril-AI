"use client";
import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Image as ImageIcon, Clock, Link2, Loader2, Mic, Plus, Puzzle, RadioTower, Shield, Smartphone, Sparkles, X, XCircle } from "lucide-react";
import { toast } from "sonner";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { SmsConnectionPanel } from "./SmsConnectionPanel";
import { SkeletonCard } from "../components/skeleton";
import { OperatorToggle } from "../../../components/operator-toggle";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...auth, ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || "Request failed");
  }
  return res.json() as Promise<T>;
}

type RetrievalMode = "semantic" | "keyword" | "hybrid";
type ReplyLanguageMode = "mirror" | "tanglish" | "english" | "tamil" | "tanglish_escalate_tamil";
type VoiceSettingKey = "ai_voice_reply_speaker";
const IDLE_CLOSE_DAYS_MIN = 2;
const IDLE_CLOSE_DAYS_MAX = 90;
const IDLE_CLOSE_DAYS_DEFAULT = 30;

type MediaRecommendationSettingKey = "ai_media_recommendations_enabled" | "catalog_ai_max_images_ceiling";

type ReplyModelId = "google/gemini-3.1-flash-lite" | "google/gemini-3.5-flash-lite";

type AiProviderKey = "gemini" | "jina";

// Replies run on Gemini only; Jina does knowledge-base and catalog search. Each needs its
// own API key per client -- there is no platform-wide fallback key. (Same model list as
// REPLY_MODELS in backend/app/services/ai_reply.py.)
const AI_PROVIDERS: { key: AiProviderKey; label: string; credKey: string; settingKey: string }[] = [
  { key: "gemini", label: "Gemini", credKey: "ai_gemini", settingKey: "gemini_api_key" },
  { key: "jina", label: "Jina", credKey: "ai_jina", settingKey: "jina_api_key" },
];

const REPLY_MODELS: { id: ReplyModelId; label: string; provider: AiProviderKey; desc: string }[] = [
  { id: "google/gemini-3.1-flash-lite", label: "Gemini 3.1 Flash Lite", provider: "gemini", desc: "The default. Cheap and fast, good general quality." },
  { id: "google/gemini-3.5-flash-lite", label: "Gemini 3.5 Flash Lite", provider: "gemini", desc: "The newer Flash Lite generation." },
];

// Keys already surfaced as their own checkbox in the client sidebar (see ../sidebar.tsx's
// PRODUCT_NAV/TC_SUB_NAV toggleKey/featureKey values, plus the deps handleToggleFeature
// cascades in ../page.tsx). Hidden here so this raw editor can't drift out of sync with
// those dedicated, cascade-aware controls -- this panel is only for flags with no UI of
// their own, e.g. a one-off client integration like AstroTamil's astro_bridge.
const MANAGED_FEATURE_KEYS = new Set([
  "inbound_leads", "outbound_leads",
  "telecalling", "telecalling.upload", "telecalling.dialer", "telecalling.scheduled", "telecalling.notes",
  "whatsapp", "analytics", "sms",
]);

// Ops-entered, not client self-service: astro_bridge_url/api_key are issued by the
// astrologer's own Django backend and astro_bridge_secret must match its
// AIRA_BRIDGE_SECRET, so setting this up is a coordination task between Aira's team
// and that platform's devs, not something a client's staff can meaningfully fill in
// themselves. Mirrors astro_bridge.py's exact 3 keys -- see get_setting() call sites.
type AstroBridgeFieldKey = "astro_bridge_url" | "astro_bridge_api_key" | "astro_bridge_secret";

const ASTRO_BRIDGE_FIELDS: { key: AstroBridgeFieldKey; label: string; secret: boolean; hint: string }[] = [
  { key: "astro_bridge_url", label: "Partner app base URL", secret: false, hint: "Base URL of the client's own app, e.g. https://app.example.com — no trailing slash. Only needed for expert hand-off." },
  { key: "astro_bridge_api_key", label: "Partner app API key", secret: true, hint: "Issued by the client's app. Anril sends it as X-API-Key on every hand-off push." },
  { key: "astro_bridge_secret", label: "Shared secret (signing)", secret: true, hint: "HMAC secret the client's app signs every request to Anril with (partner sends and the reply callback). Hand it to their developer; their Developer page says whether it is on file." },
];

const RETRIEVAL_MODES: { id: RetrievalMode; label: string; desc: string }[] = [
  { id: "semantic", label: "Smart", desc: "Understands meaning & language (Tamil/English), even when a lead rephrases. Recommended." },
  { id: "keyword", label: "Exact words", desc: "Matches the exact words in your documents. Fastest, no AI cost — weaker on reworded questions." },
  { id: "hybrid", label: "Best of both", desc: "Blends meaning + exact words for the highest accuracy." },
];

// Forced modes bypass the script-mismatch safety net entirely (there's nothing to
// "correct" -- the reply script is intentional), so they always send exactly what the
// model generates. Only "mirror" keeps the auto-regeneration check that catches a reply
// drifting to the wrong script.
const REPLY_LANGUAGE_MODES: { id: ReplyLanguageMode; label: string; desc: string }[] = [
  { id: "mirror", label: "Mirror lead's language", desc: "Matches whatever the lead writes in — English, Tamil script, or Tanglish. Default." },
  { id: "tanglish", label: "Tanglish only", desc: "Always replies in Tanglish (Tamil words in Roman letters), regardless of what the lead writes in." },
  { id: "tanglish_escalate_tamil", label: "Tanglish, lock to Tamil on request", desc: "Replies in Tanglish by default. If the lead asks — in Tamil script — to be spoken to in Tamil, permanently switches to native Tamil script for the rest of that conversation. A lead simply answering in Tamil script does not trigger the switch." },
  { id: "english", label: "English only", desc: "Always replies in English, regardless of what the lead writes in." },
  { id: "tamil", label: "Tamil script only", desc: "Always replies in native Tamil script, regardless of what the lead writes in." },
];

// Gemini's full set of prebuilt TTS voices. Only "Kore" has been live-tested for Tamil/
// Tanglish accent authenticity (see subsystem-notes.md 2026-07-13/14) -- the others carry
// the same language-handling capability (Gemini's TTS is LLM-native, not phoneme-based
// per-voice), but their specific vocal character for Tanglish hasn't been individually
// verified.
const VOICE_SPEAKERS = [
  { value: "Kore", label: "Kore (Firm) -- live-tested for Tamil" },
  { value: "Zephyr", label: "Zephyr (Bright)" },
  { value: "Puck", label: "Puck (Upbeat)" },
  { value: "Charon", label: "Charon (Informative)" },
  { value: "Fenrir", label: "Fenrir (Excitable)" },
  { value: "Leda", label: "Leda (Youthful)" },
  { value: "Orus", label: "Orus (Firm)" },
  { value: "Aoede", label: "Aoede (Breezy)" },
  { value: "Callirrhoe", label: "Callirrhoe (Easy-going)" },
  { value: "Autonoe", label: "Autonoe (Bright)" },
  { value: "Enceladus", label: "Enceladus (Breathy)" },
  { value: "Iapetus", label: "Iapetus (Clear)" },
  { value: "Umbriel", label: "Umbriel (Easy-going)" },
  { value: "Algieba", label: "Algieba (Smooth)" },
  { value: "Despina", label: "Despina (Smooth)" },
  { value: "Erinome", label: "Erinome (Clear)" },
  { value: "Algenib", label: "Algenib (Gravelly)" },
  { value: "Rasalgethi", label: "Rasalgethi (Informative)" },
  { value: "Laomedeia", label: "Laomedeia (Upbeat)" },
  { value: "Achernar", label: "Achernar (Soft)" },
  { value: "Alnilam", label: "Alnilam (Firm)" },
  { value: "Schedar", label: "Schedar (Even)" },
  { value: "Gacrux", label: "Gacrux (Mature)" },
  { value: "Pulcherrima", label: "Pulcherrima (Forward)" },
  { value: "Achird", label: "Achird (Friendly)" },
  { value: "Zubenelgenubi", label: "Zubenelgenubi (Casual)" },
  { value: "Vindemiatrix", label: "Vindemiatrix (Gentle)" },
  { value: "Sadachbia", label: "Sadachbia (Lively)" },
  { value: "Sadaltager", label: "Sadaltager (Knowledgeable)" },
  { value: "Sulafat", label: "Sulafat (Warm)" },
];

interface ConfigData {
  master_prompt: string;
  business_description: string;
  credentials_status: Record<string, "configured" | "incomplete" | "not_configured">;
  settings: {
    ai_auto_reply_enabled: boolean;
    ai_voice_reply_enabled: boolean;
    ai_voice_reply_speaker?: string | null;
    ai_media_recommendations_enabled?: boolean;
    catalog_ai_max_images_ceiling?: number | string | null;
    kb_retrieval_mode: RetrievalMode;
    ai_reply_model: ReplyModelId | null;
    reply_language_mode: ReplyLanguageMode;
    deal_idle_close_days?: number | null;
  };
}

interface CallingProviderData {
  tenant_id: string;
  calling_provider: "telecmi" | "sim_basic";
  telecalling_enabled: boolean;
}

const CRED_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp (Meta)",
  telegram: "Telegram",
  instagram: "Instagram",
  facebook: "Facebook",
};

// Legacy/superseded credential_status keys, kept in the API response for backward
// compatibility but shown elsewhere instead of the generic Messaging Channels grid --
// per-provider AI keys render inside the AI Integrations section, and telecalling status
// is already covered by the Calling Provider card above.
const CRED_KEYS_HANDLED_ELSEWHERE = new Set(["ai", "ai_gemini", "ai_jina", "telecalling"]);

function statusBadge(status: string) {
  switch (status) {
    case "configured":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-success/10 text-success">
          <CheckCircle2 size={12} /> Configured
        </span>
      );
    case "incomplete":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-warning/10 text-warning">
          <AlertTriangle size={12} /> Incomplete
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-surface-mid text-ink-muted">
          <XCircle size={12} /> Not Configured
        </span>
      );
  }
}

export function ConfigView({ tenantId }: { tenantId: string }) {
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [provider, setProvider] = useState<CallingProviderData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [providerSaving, setProviderSaving] = useState<"telecmi" | "sim_basic" | null>(null);
  const [pendingProvider, setPendingProvider] = useState<"telecmi" | "sim_basic" | null>(null);
  const [retrievalSaving, setRetrievalSaving] = useState<RetrievalMode | null>(null);
  const [replyLanguageSaving, setReplyLanguageSaving] = useState<ReplyLanguageMode | null>(null);
  const [autoReplySaving, setAutoReplySaving] = useState(false);
  const [idleCloseDraft, setIdleCloseDraft] = useState<string | null>(null);
  const [idleCloseSaving, setIdleCloseSaving] = useState(false);
  const [voiceReplySaving, setVoiceReplySaving] = useState(false);
  const [voiceSettingSaving, setVoiceSettingSaving] = useState<VoiceSettingKey | null>(null);
  const [mediaRecommendationSaving, setMediaRecommendationSaving] = useState<MediaRecommendationSettingKey | null>(null);
  const [apiKeyDrafts, setApiKeyDrafts] = useState<Record<AiProviderKey, string>>({ gemini: "", jina: "" });
  const [apiKeySaving, setApiKeySaving] = useState<AiProviderKey | null>(null);
  const [replyModelSaving, setReplyModelSaving] = useState<ReplyModelId | null>(null);
  const [enabledFeatures, setEnabledFeatures] = useState<string[]>([]);
  const [newFeatureKey, setNewFeatureKey] = useState("");
  const [featureSaving, setFeatureSaving] = useState(false);
  const [astroBridgeDrafts, setAstroBridgeDrafts] = useState<Record<AstroBridgeFieldKey, string>>({
    astro_bridge_url: "", astro_bridge_api_key: "", astro_bridge_secret: "",
  });
  const [astroBridgeSaving, setAstroBridgeSaving] = useState<AstroBridgeFieldKey | null>(null);

  async function updateRetrievalMode(mode: RetrievalMode) {
    if (!config || config.settings.kb_retrieval_mode === mode) return;
    setRetrievalSaving(mode);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            settings: { kb_retrieval_mode: mode }
          })
        }
      );
      setConfig({
        ...config,
        settings: {
          ...config.settings,
          kb_retrieval_mode: mode
        }
      });
      toast.success(`Knowledge search mode set to "${RETRIEVAL_MODES.find(m => m.id === mode)?.label}".`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update knowledge search mode");
      toast.error("Failed to update search mode. Please try again.");
    } finally {
      setRetrievalSaving(null);
    }
  }

  async function updateReplyLanguageMode(mode: ReplyLanguageMode) {
    if (!config || config.settings.reply_language_mode === mode) return;
    setReplyLanguageSaving(mode);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            settings: { reply_language_mode: mode }
          })
        }
      );
      setConfig({
        ...config,
        settings: {
          ...config.settings,
          reply_language_mode: mode
        }
      });
      toast.success(`Reply language set to "${REPLY_LANGUAGE_MODES.find(m => m.id === mode)?.label}".`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update reply language");
      toast.error("Failed to update reply language. Please try again.");
    } finally {
      setReplyLanguageSaving(null);
    }
  }

  async function saveIdleCloseDays() {
    if (!config || idleCloseDraft === null) return;
    const days = Number(idleCloseDraft);
    if (!Number.isInteger(days) || days < IDLE_CLOSE_DAYS_MIN || days > IDLE_CLOSE_DAYS_MAX) {
      toast.error(`Enter a whole number from ${IDLE_CLOSE_DAYS_MIN} to ${IDLE_CLOSE_DAYS_MAX}.`);
      return;
    }
    setIdleCloseSaving(true);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            settings: { deal_idle_close_days: String(days) }
          })
        }
      );
      setConfig({
        ...config,
        settings: {
          ...config.settings,
          deal_idle_close_days: days
        }
      });
      setIdleCloseDraft(null);
      toast.success(`Unpaid deals now close after ${days} idle days.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update the idle-close setting.");
    } finally {
      setIdleCloseSaving(false);
    }
  }

  async function updateReplyModel(model: ReplyModelId) {
    if (!config || config.settings.ai_reply_model === model) return;
    setReplyModelSaving(model);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            settings: { ai_reply_model: model }
          })
        }
      );
      setConfig({
        ...config,
        settings: {
          ...config.settings,
          ai_reply_model: model
        }
      });
      toast.success(`Conversational reply model set to "${REPLY_MODELS.find(m => m.id === model)?.label}".`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update reply model");
      toast.error("Failed to update reply model. Please try again.");
    } finally {
      setReplyModelSaving(null);
    }
  }

  async function updateAutoReply(enabled: boolean) {
    // No early-return-if-unchanged guard here: the displayed value can be stale relative
    // to the DB (e.g. a never-configured tenant defaults to enabled on the backend but a
    // naive `== "true"` read shows Off) -- a guard keyed off that display would silently
    // no-op the very click meant to fix it. Live-confirmed 2026-07-17: this was exactly
    // why clicking "Off" for a never-configured tenant sent no request at all.
    if (!config) return;
    setAutoReplySaving(true);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            settings: { ai_auto_reply_enabled: enabled }
          })
        }
      );
      setConfig({
        ...config,
        settings: {
          ...config.settings,
          ai_auto_reply_enabled: enabled
        }
      });
      toast.success(enabled ? "AI auto-reply enabled for this client." : "AI auto-reply disabled for this client.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update AI auto-reply");
      toast.error("Failed to update AI auto-reply.");
    } finally {
      setAutoReplySaving(false);
    }
  }

  async function updateVoiceReplies(enabled: boolean) {
    // Same reasoning as updateAutoReply -- no stale-display guard, always send the PATCH.
    if (!config) return;
    setVoiceReplySaving(true);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            settings: { ai_voice_reply_enabled: enabled }
          })
        }
      );
      setConfig({
        ...config,
        settings: {
          ...config.settings,
          ai_voice_reply_enabled: enabled
        }
      });
      toast.success(enabled ? "AI voice replies enabled for this client." : "AI voice replies disabled for this client.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update AI voice replies");
      toast.error("Failed to update AI voice replies.");
    } finally {
      setVoiceReplySaving(false);
    }
  }

  async function updateVoiceSetting(key: VoiceSettingKey, value: string) {
    if (!config || (config.settings[key] ?? "") === value) return;
    setVoiceSettingSaving(key);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            settings: { [key]: value }
          })
        }
      );
      setConfig({
        ...config,
        settings: {
          ...config.settings,
          [key]: value
        }
      });
      toast.success("AI voice reply setting updated.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update AI voice reply setting");
      toast.error("Failed to update AI voice reply setting.");
    } finally {
      setVoiceSettingSaving(null);
    }
  }

  async function updateMediaRecommendationSetting(key: MediaRecommendationSettingKey, value: string | boolean) {
    if (!config || (config.settings[key] ?? "") === value) return;
    setMediaRecommendationSaving(key);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            settings: { [key]: value }
          })
        }
      );
      setConfig({
        ...config,
        settings: {
          ...config.settings,
          [key]: value
        }
      });
      toast.success("AI media recommendation setting updated.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update AI media recommendation setting");
      toast.error("Failed to update AI media recommendation setting.");
    } finally {
      setMediaRecommendationSaving(null);
    }
  }

  async function updateProviderApiKey(provider: AiProviderKey) {
    const meta = AI_PROVIDERS.find((p) => p.key === provider)!;
    const value = apiKeyDrafts[provider].trim();
    if (!config || !value) return;
    setApiKeySaving(provider);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        {
          method: "PATCH",
          body: JSON.stringify({ settings: { [meta.settingKey]: value } })
        }
      );
      setApiKeyDrafts((prev) => ({ ...prev, [provider]: "" }));
      setConfig({
        ...config,
        credentials_status: {
          ...config.credentials_status,
          [meta.credKey]: "configured",
        }
      });
      toast.success(`${meta.label} API key saved.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to update ${meta.label} API key`);
      toast.error(`Failed to update ${meta.label} API key.`);
    } finally {
      setApiKeySaving(null);
    }
  }

  useEffect(() => {
    Promise.all([
      apiFetch<ConfigData>(`/api/v1/operator/clients/${tenantId}/config`),
      apiFetch<CallingProviderData>(`/api/v1/operator/clients/${tenantId}/calling-provider`),
      apiFetch<{ tenant: { enabled_features: string[] } }>(`/api/v1/operator/clients/${tenantId}/overview`),
    ])
      .then(([configData, providerData, overviewData]) => {
        setConfig(configData);
        setProvider(providerData);
        setEnabledFeatures(overviewData.tenant.enabled_features || []);
      })
      .catch(e => setError(e instanceof Error ? e.message : "Failed to load config"))
      .finally(() => setLoading(false));
  }, [tenantId]);

  async function addCustomFeature() {
    const key = newFeatureKey.trim().toLowerCase();
    if (!key) return;
    if (!/^[a-z0-9._-]+$/.test(key)) {
      toast.error("Feature keys can only contain lowercase letters, numbers, dots, underscores and hyphens.");
      return;
    }
    if (enabledFeatures.includes(key)) {
      toast.error(`"${key}" is already enabled for this client.`);
      return;
    }
    setFeatureSaving(true);
    try {
      const updated = [...enabledFeatures, key];
      await apiFetch<{ enabled_features: string[] }>(
        `/api/v1/operator/clients/${tenantId}/features`,
        { method: "PATCH", body: JSON.stringify({ features: updated }) },
      );
      setEnabledFeatures(updated);
      setNewFeatureKey("");
      toast.success(`"${key}" enabled for this client.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to add feature flag");
    } finally {
      setFeatureSaving(false);
    }
  }

  async function toggleSms(enabled: boolean) {
    setFeatureSaving(true);
    try {
      const updated = enabled ? [...enabledFeatures.filter((feature) => feature !== "sms"), "sms"] : enabledFeatures.filter((feature) => feature !== "sms");
      const data = await apiFetch<{ enabled_features: string[] }>(`/api/v1/operator/clients/${tenantId}/features`, {
        method: "PATCH", body: JSON.stringify({ features: updated }),
      });
      setEnabledFeatures(data.enabled_features);
      toast.success(enabled ? "SMS enabled." : "SMS disabled.");
    } catch (err) { toast.error(err instanceof Error ? err.message : "Couldn't update SMS access."); }
    finally { setFeatureSaving(false); }
  }

  async function removeCustomFeature(key: string) {
    setFeatureSaving(true);
    try {
      const updated = enabledFeatures.filter(f => f !== key);
      await apiFetch<{ enabled_features: string[] }>(
        `/api/v1/operator/clients/${tenantId}/features`,
        { method: "PATCH", body: JSON.stringify({ features: updated }) },
      );
      setEnabledFeatures(updated);
      toast.success(`"${key}" disabled for this client.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to remove feature flag");
    } finally {
      setFeatureSaving(false);
    }
  }

  async function saveAstroBridgeField(key: AstroBridgeFieldKey) {
    const value = astroBridgeDrafts[key].trim();
    if (!value) return;
    setAstroBridgeSaving(key);
    setError(null);
    try {
      await apiFetch<{ status: string }>(
        `/api/v1/operator/clients/${tenantId}/config`,
        { method: "PATCH", body: JSON.stringify({ settings: { [key]: value } }) },
      );
      setAstroBridgeDrafts((prev) => ({ ...prev, [key]: "" }));
      // Refetch rather than guess: the aggregate "astro_bridge" status depends on all
      // 3 fields, and this component only tracks drafts for the one just saved.
      const refreshed = await apiFetch<ConfigData>(`/api/v1/operator/clients/${tenantId}/config`);
      setConfig(refreshed);
      toast.success("Partner integration field saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save astro bridge field");
      toast.error("Failed to save astro bridge field.");
    } finally {
      setAstroBridgeSaving(null);
    }
  }

  async function updateProvider(callingProvider: "telecmi" | "sim_basic") {
    if (!provider || provider.calling_provider === callingProvider) return;
    setProviderSaving(callingProvider);
    setError(null);
    try {
      const saved = await apiFetch<{ tenant_id: string; calling_provider: "telecmi" | "sim_basic" }>(
        `/api/v1/operator/clients/${tenantId}/calling-provider`,
        { method: "PATCH", body: JSON.stringify({ calling_provider: callingProvider }) },
      );
      setProvider({ ...provider, calling_provider: saved.calling_provider });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update calling provider");
    } finally {
      setProviderSaving(null);
    }
  }

  const pendingProviderCopy = pendingProvider === "sim_basic"
    ? {
        title: "Switch to SIM Basic?",
        description: "This client will use mobile SIM calling with manual call wrap-up. Cloud Telephony agent credentials, automatic recordings, and exact provider call duration will no longer drive new calls.",
        confirm: "Switch to SIM Basic",
      }
    : {
        title: "Switch to Cloud Telephony?",
        description: "This client will use Cloud Telephony click-to-call. Telecallers need Cloud Telephony User ID/password, and recordings/durations come from Cloud Telephony webhooks.",
        confirm: "Switch to Cloud Telephony",
      };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-danger/20 rounded-xl text-sm text-danger">
        {error}
      </div>
    );
  }

  if (!config) return null;

  const voiceSettings = {
    speaker: config.settings.ai_voice_reply_speaker ?? "Kore",
  };
  const mediaRecommendationsEnabled = config.settings.ai_media_recommendations_enabled ?? false;
  const mediaMaxImagesCeiling = Number(config.settings.catalog_ai_max_images_ceiling ?? 5);
  const idleCloseSaved = config.settings.deal_idle_close_days ?? IDLE_CLOSE_DAYS_DEFAULT;
  const idleCloseValue = idleCloseDraft ?? String(idleCloseSaved);
  const idleCloseDirty = idleCloseDraft !== null && idleCloseDraft.trim() !== String(idleCloseSaved);
  const customFeatureKeys = enabledFeatures.filter(f => !MANAGED_FEATURE_KEYS.has(f));

  return (
    <div className="space-y-6">
      <SmsConnectionPanel tenantId={tenantId} enabled={enabledFeatures.includes("sms")} featureSaving={featureSaving} onToggle={(enabled) => void toggleSms(enabled)} />
      {/* Calling Provider */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <RadioTower size={16} className="text-ink-muted" />
          Calling Provider
        </h3>
        <div className="grid gap-4 md:grid-cols-2">
          {[
            {
              id: "telecmi" as const,
              title: "Cloud Telephony",
              desc: "API calling with automatic call logs, duration, recordings, and webhooks.",
              icon: RadioTower,
            },
            {
              id: "sim_basic" as const,
              title: "SIM Basic",
              desc: "Mobile SIM calling with manual wrap-up, duration, and notes.",
              icon: Smartphone,
            },
          ].map((option) => {
            const Icon = option.icon;
            const selected = provider?.calling_provider === option.id;
            const saving = providerSaving === option.id;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => {
                  if (provider?.calling_provider !== option.id) setPendingProvider(option.id);
                }}
                disabled={!!providerSaving}
                className={`rounded-card border p-4 text-left shadow-sm transition-all ${
                  selected
                    ? "border-primary bg-primary-light text-ink ring-1 ring-primary/10"
                    : "border-border bg-white hover:border-primary-muted"
                } ${providerSaving ? "opacity-70" : ""}`}
              >
                <div className="flex items-start gap-3">
                  <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${selected ? "bg-white text-primary" : "bg-surface-mid text-ink-muted"}`}>
                    {saving ? <Loader2 size={18} className="animate-spin" /> : <Icon size={18} />}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-ink">{option.title}</p>
                      {selected && statusBadge("configured")}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-ink-muted">{option.desc}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {pendingProvider && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-card bg-white p-6 shadow-xl">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-warning/10 text-warning">
                <AlertTriangle size={20} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-ink">{pendingProviderCopy.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-secondary">{pendingProviderCopy.description}</p>
              </div>
            </div>
            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={() => setPendingProvider(null)}
                disabled={!!providerSaving}
                className="flex-1 rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-ink-secondary transition-colors hover:bg-surface-mid disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  const next = pendingProvider;
                  await updateProvider(next);
                  setPendingProvider(null);
                }}
                disabled={!!providerSaving}
                className="flex-1 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {providerSaving ? <Loader2 size={16} className="mx-auto animate-spin" /> : pendingProviderCopy.confirm}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Messaging Channels */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Shield size={16} className="text-ink-muted" />
          Messaging Channels
        </h3>
        <div className="grid grid-cols-2 gap-4">
          {Object.entries(config.credentials_status)
            .filter(([provider]) => !CRED_KEYS_HANDLED_ELSEWHERE.has(provider))
            .map(([provider, status]) => (
              <div key={provider} className="bg-white rounded-card border border-border p-4 shadow-sm">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-ink">{CRED_LABELS[provider] || provider}</p>
                  {statusBadge(status)}
                </div>
              </div>
          ))}
        </div>
      </div>

      <p className="text-xs text-ink-muted">
        Usage counts for these AI features are on the <span className="font-medium text-ink-secondary">Entitlements &amp; Usage</span> tab.
      </p>

      {/* AI Auto-Reply */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Sparkles size={16} className="text-ink-muted" />
          AI Auto-Reply
        </h3>
        <div className="rounded-card border border-border bg-white p-4 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">Auto-reply to inbound messages</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-muted">
                Allow Anril to automatically reply to inbound WhatsApp messages using AI for this client.
              </p>
            </div>
            <OperatorToggle
              checked={config.settings.ai_auto_reply_enabled}
              onChange={updateAutoReply}
              loading={autoReplySaving}
              aria-label="Toggle AI auto-reply"
            />
          </div>
        </div>
      </div>

      {/* AI Voice Replies */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Mic size={16} className="text-ink-muted" />
          AI Voice Replies
        </h3>
        <div className="rounded-card border border-border bg-white p-4 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">Reply with WhatsApp audio</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-muted">
                When a customer sends a WhatsApp voice note, Anril transcribes it and replies back as a Gemini-generated voice note for this client.
              </p>
            </div>
            <OperatorToggle
              checked={config.settings.ai_voice_reply_enabled}
              onChange={updateVoiceReplies}
              loading={voiceReplySaving}
              disabled={!config.settings.ai_auto_reply_enabled}
              aria-label="Toggle AI voice replies"
            />
          </div>
          {!config.settings.ai_auto_reply_enabled && (
            <p className="mt-3 text-xs text-warning">Enable AI Auto-Reply before turning on voice replies.</p>
          )}
          <div className="mt-4 border-t border-border-subtle pt-4">
            <label className="block">
              <span className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                <Mic size={13} /> Voice
              </span>
              <select
                value={voiceSettings.speaker}
                onChange={(e) => updateVoiceSetting("ai_voice_reply_speaker", e.target.value)}
                disabled={voiceSettingSaving === "ai_voice_reply_speaker"}
                className="w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary disabled:opacity-60"
              >
                {VOICE_SPEAKERS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </div>

      {/* AI Media Recommendations */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <ImageIcon size={16} className="text-ink-muted" />
          AI Media Recommendations
        </h3>
        <div className="rounded-card border border-border bg-white p-4 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">Recommend catalog images</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-muted">
                Master switch for this client&apos;s catalog AI recommendations. When off, recommendations are hard-disabled regardless of what the client has chosen in their own catalog settings. The client controls whether it&apos;s on and how many images per reply within the ceiling below.
              </p>
            </div>
            <OperatorToggle
              checked={mediaRecommendationsEnabled}
              onChange={(checked) => updateMediaRecommendationSetting("ai_media_recommendations_enabled", checked)}
              loading={mediaRecommendationSaving === "ai_media_recommendations_enabled"}
              aria-label="Toggle AI media recommendations"
            />
          </div>
          <div className="mt-4 border-t border-border-subtle pt-4">
            <label className="block">
              <span className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                <ImageIcon size={13} /> Maximum images ceiling
              </span>
              <select
                value={Number.isFinite(mediaMaxImagesCeiling) ? String(mediaMaxImagesCeiling) : "5"}
                onChange={(e) => updateMediaRecommendationSetting("catalog_ai_max_images_ceiling", e.target.value)}
                disabled={mediaRecommendationSaving === "catalog_ai_max_images_ceiling"}
                className="w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary disabled:opacity-60"
              >
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((count) => (
                  <option key={count} value={count}>{count}</option>
                ))}
              </select>
              <span className="mt-1 block text-[11px] text-ink-muted">The client can choose any value up to this; they can never exceed it.</span>
            </label>
          </div>
        </div>
      </div>

      {/* Knowledge Search Mode */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Sparkles size={16} className="text-ink-muted" />
          Knowledge Search Mode
        </h3>
        <div className="grid gap-4 md:grid-cols-3">
          {RETRIEVAL_MODES.map((option) => {
            const selected = config.settings.kb_retrieval_mode === option.id;
            const saving = retrievalSaving === option.id;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => updateRetrievalMode(option.id)}
                disabled={!!retrievalSaving || selected}
                className={`rounded-card border p-4 text-left shadow-sm transition-all ${
                  selected
                    ? "border-primary bg-primary-light text-ink ring-1 ring-primary/10"
                    : "border-border bg-white hover:border-primary-muted"
                } ${retrievalSaving && !saving ? "opacity-70" : ""} disabled:cursor-default`}
              >
                <div className="flex items-start gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 justify-between">
                      <p className="text-sm font-semibold text-ink">{option.label}</p>
                      {saving && <Loader2 size={14} className="animate-spin text-primary" />}
                      {selected && !saving && (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-success/10 text-success">
                          Active
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-ink-muted">{option.desc}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* The master prompt is platform-wide: it is shown and edited only at
          /operator/prompt-template, not repeated under every client. */}
      <div>
        <div className="rounded-card border border-border bg-surface-low p-4 shadow-sm">
          <p className="mb-2 text-xs font-semibold text-ink">
            Client&apos;s product description (read-only)
          </p>
          <pre className="whitespace-pre-wrap font-body text-xs leading-relaxed text-ink-muted">
            {config.business_description || "The client has not written a description yet."}
          </pre>
        </div>
      </div>

      {/* Reply Language */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Sparkles size={16} className="text-ink-muted" />
          Reply Language
        </h3>
        <p className="mb-4 text-xs leading-relaxed text-ink-muted">
          Controls what language/script AI replies use. Change this if the client asks for a fixed reply language instead of matching each lead.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          {REPLY_LANGUAGE_MODES.map((option) => {
            const selected = config.settings.reply_language_mode === option.id;
            const saving = replyLanguageSaving === option.id;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => updateReplyLanguageMode(option.id)}
                disabled={!!replyLanguageSaving || selected}
                className={`rounded-card border p-4 text-left shadow-sm transition-all ${
                  selected
                    ? "border-primary bg-primary-light text-ink ring-1 ring-primary/10"
                    : "border-border bg-white hover:border-primary-muted"
                } ${replyLanguageSaving && !saving ? "opacity-70" : ""} disabled:cursor-default`}
              >
                <div className="flex items-start gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 justify-between">
                      <p className="text-sm font-semibold text-ink">{option.label}</p>
                      {saving && <Loader2 size={14} className="animate-spin text-primary" />}
                      {selected && !saving && (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-success/10 text-success">
                          Active
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-ink-muted">{option.desc}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Deal idle-close window */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Clock size={16} className="text-ink-muted" />
          Unpaid Deals
        </h3>
        <div className="flex items-end gap-3 rounded-card border border-border bg-white p-4 shadow-sm">
          <label className="block min-w-0 flex-1">
            <span className="mb-1.5 block text-xs font-medium text-ink-muted">Close unpaid deals after (days idle)</span>
            <input
              type="number"
              inputMode="numeric"
              min={IDLE_CLOSE_DAYS_MIN}
              max={IDLE_CLOSE_DAYS_MAX}
              step={1}
              value={idleCloseValue}
              onChange={(e) => setIdleCloseDraft(e.target.value)}
              disabled={idleCloseSaving}
              className="w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary disabled:opacity-60"
            />
            <span className="mt-1 block text-[11px] leading-relaxed text-ink-muted">
              2–90 days. A lead message or real progress resets the clock.
            </span>
          </label>
          <button
            type="button"
            onClick={saveIdleCloseDays}
            disabled={idleCloseSaving || !idleCloseDirty}
            className="inline-flex h-10 items-center justify-center rounded-xl bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-surface-mid disabled:text-ink-muted"
          >
            {idleCloseSaving ? <Loader2 size={16} className="animate-spin" /> : "Save"}
          </button>
        </div>
      </div>

      {/* AI Integrations */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Sparkles size={16} className="text-ink-muted" />
          AI Integrations
        </h3>
        <p className="mb-4 text-xs leading-relaxed text-ink-muted">
          Replies run on Gemini, with this client&apos;s own API key — there is no shared platform key. The highlighted model generates auto-replies, reengagement messages, and product-recommendation replies. If Google fails on that model, the same message is tried once on the other one.
        </p>
        <div className="flex flex-col gap-5">
          {AI_PROVIDERS.map((providerMeta) => {
            const status = config.credentials_status[providerMeta.credKey] || "not_configured";
            const draft = apiKeyDrafts[providerMeta.key];
            const savingKey = apiKeySaving === providerMeta.key;
            const models = REPLY_MODELS.filter((m) => m.provider === providerMeta.key);
            return (
              <div key={providerMeta.key} className="rounded-card border border-border bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between mb-3">
                  <p className="text-sm font-semibold text-ink">{providerMeta.label}</p>
                  {statusBadge(status)}
                </div>
                <div className="flex flex-col gap-3 md:flex-row md:items-end mb-4">
                  <label className="block min-w-0 flex-1">
                    <span className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                      <Sparkles size={13} /> {providerMeta.label} API Key
                    </span>
                    <input
                      type="password"
                      value={draft}
                      onChange={(e) => setApiKeyDrafts((prev) => ({ ...prev, [providerMeta.key]: e.target.value }))}
                      placeholder={status === "configured" ? "Configured — enter a new key to replace" : `Paste this client's ${providerMeta.label} API key`}
                      disabled={savingKey}
                      className="w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-ink-muted focus:border-primary disabled:opacity-60"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => updateProviderApiKey(providerMeta.key)}
                    disabled={savingKey || !draft.trim()}
                    className="inline-flex h-10 items-center justify-center rounded-xl bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-surface-mid disabled:text-ink-muted"
                  >
                    {savingKey ? <Loader2 size={16} className="animate-spin" /> : "Save Key"}
                  </button>
                </div>
                {providerMeta.key === "jina" && status !== "configured" && (
                  <p className="mb-3 flex items-start gap-1.5 text-xs text-warning">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                    No Jina key: this client&apos;s knowledge files are not searchable (Anril pastes all files into every reply).
                  </p>
                )}
                {models.length === 0 ? (
                  <p className="text-xs leading-relaxed text-ink-muted">
                    Used for knowledge-base and catalog search embeddings — no reply model choice for this provider.
                  </p>
                ) : (
                <div className="grid gap-3 md:grid-cols-2">
                  {models.map((option) => {
                    const selected = config.settings.ai_reply_model === option.id;
                    const saving = replyModelSaving === option.id;
                    return (
                      <button
                        key={option.id}
                        type="button"
                        onClick={() => updateReplyModel(option.id)}
                        disabled={!!replyModelSaving || selected}
                        className={`rounded-card border p-3 text-left shadow-sm transition-all ${
                          selected
                            ? "border-primary bg-primary-light text-ink ring-1 ring-primary/10"
                            : "border-border bg-white hover:border-primary-muted"
                        } ${replyModelSaving && !saving ? "opacity-70" : ""} disabled:cursor-default`}
                      >
                        <div className="flex items-center gap-2 justify-between">
                          <p className="text-sm font-semibold text-ink">{option.label}</p>
                          {saving && <Loader2 size={14} className="animate-spin text-primary" />}
                          {selected && !saving && (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-success/10 text-success">
                              Active
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-ink-muted">{option.desc}</p>
                      </button>
                    );
                  })}
                </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Partner integration (settings keys keep their original astro_bridge_* names) */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Link2 size={16} className="text-ink-muted" />
          Partner integration
          {statusBadge(config.credentials_status.astro_bridge || "not_configured")}
        </h3>
        <p className="mb-4 text-xs leading-relaxed text-ink-muted">
          How this client&apos;s own app talks to Anril. The <strong>shared secret</strong> is all a
          client needs to send WhatsApp templates and texts through Anril from their app; their
          developer reads the contract on the dashboard&apos;s <strong>Developer</strong> page, which
          shows whether a secret is on file but never its value. The URL and API key are only for
          expert hand-off (Anril pushing paid requests to their app), which also needs the
          <code className="rounded bg-surface-low px-1 py-0.5 text-[11px]">astro_bridge</code> flag
          below under Custom Feature Flags. Ops-entered, not client self-service.
        </p>
        <div className="flex flex-col gap-5">
          {ASTRO_BRIDGE_FIELDS.map((field) => {
            const draft = astroBridgeDrafts[field.key];
            const saving = astroBridgeSaving === field.key;
            return (
              <div key={field.key} className="rounded-card border border-border bg-white p-4 shadow-sm">
                <div className="flex flex-col gap-3 md:flex-row md:items-end">
                  <label className="block min-w-0 flex-1">
                    <span className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                      <Link2 size={13} /> {field.label}
                    </span>
                    <input
                      type={field.secret ? "password" : "text"}
                      value={draft}
                      onChange={(e) => setAstroBridgeDrafts((prev) => ({ ...prev, [field.key]: e.target.value }))}
                      placeholder={field.secret ? "Enter a new value to set or replace" : "https://astro.example.com"}
                      disabled={saving}
                      className="w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-ink-muted focus:border-primary disabled:opacity-60"
                    />
                    <span className="mt-1 block text-[11px] leading-relaxed text-ink-muted">{field.hint}</span>
                  </label>
                  <button
                    type="button"
                    onClick={() => saveAstroBridgeField(field.key)}
                    disabled={saving || !draft.trim()}
                    className="inline-flex h-10 items-center justify-center rounded-xl bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-surface-mid disabled:text-ink-muted"
                  >
                    {saving ? <Loader2 size={16} className="animate-spin" /> : "Save"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Custom Feature Flags */}
      <div>
        <h3 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
          <Puzzle size={16} className="text-ink-muted" />
          Custom Feature Flags
        </h3>
        <p className="mb-4 text-xs leading-relaxed text-ink-muted">
          Raw flags with no plan/catalog entry of their own — for a one-off integration built
          for a specific client, like a paid-request hand-off to the client&apos;s own expert
          platform (<code className="rounded bg-surface-low px-1 py-0.5 text-[11px]">astro_bridge</code>).
          If another client needs a similar custom connection, enable a flag here and the
          matching setup fields appear for them under Settings → Connect Channels.
        </p>
        <div className="rounded-card border border-border bg-white p-4 shadow-sm">
          <div className="flex flex-wrap gap-2 mb-4">
            {customFeatureKeys.length === 0 && (
              <p className="text-xs text-ink-muted">No custom flags enabled for this client.</p>
            )}
            {customFeatureKeys.map((key) => (
              <span
                key={key}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-low px-3 py-1 text-xs font-medium text-ink"
              >
                {key}
                <button
                  type="button"
                  onClick={() => removeCustomFeature(key)}
                  disabled={featureSaving}
                  aria-label={`Disable ${key}`}
                  className="text-ink-muted transition-colors hover:text-danger disabled:opacity-50"
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={newFeatureKey}
              onChange={(e) => setNewFeatureKey(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addCustomFeature(); }}
              placeholder="e.g. astro_bridge"
              disabled={featureSaving}
              className="flex-1 rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-ink-muted focus:border-primary disabled:opacity-60"
            />
            <button
              type="button"
              onClick={addCustomFeature}
              disabled={featureSaving || !newFeatureKey.trim()}
              className="inline-flex h-10 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-surface-mid disabled:text-ink-muted"
            >
              {featureSaving ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
              Enable
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
