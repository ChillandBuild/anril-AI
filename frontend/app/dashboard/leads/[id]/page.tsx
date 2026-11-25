"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import {
  BellOff,
  Tag as TagIcon,
  CalendarCheck,
  CalendarX,
  IndianRupee,
  Megaphone,
  MessageCircle,
  Phone,
  Plus,
  RefreshCw,
  RotateCcw,
  ShoppingBag,
  Star,
  UserPlus,
  X,
  type LucideIcon,
} from "lucide-react";
import { api, CustomerEvent, CustomerProfile } from "@/lib/api";
import {
  TIMELINE_CHIPS,
  bookingStatusWords,
  cleanTag,
  describeTagResult,
  eventMatchesChip,
  parseTagInput,
  refundMethodWords,
  starsText,
  tagsApi,
  MAX_TAGS_PER_PERSON,
  type BookingEventFields,
  type ChipKey,
  type CustomerProfileExtras,
  type ExtraCustomerEvent,
} from "@/lib/customersApi";
import { ConfirmModal } from "@/components/ConfirmModal";
import { InterestedIn } from "@/components/chats/InterestedIn";
import { cn } from "@/lib/utils";
import { useAuthRole } from "../../contexts/AuthRoleContext";

/** The profile as the backend now sends it: new event kinds, extra totals and tags (all optional on an older backend). */
type AnyEvent = CustomerEvent | ExtraCustomerEvent;
type ProfileX = Omit<CustomerProfile, "timeline"> & CustomerProfileExtras & { timeline: AnyEvent[] };

const SOURCE_LABELS: Partial<Record<string, string>> = {
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  facebook: "Facebook",
  telegram: "Telegram",
  meta_form: "Instant form",
  qr: "QR",
  indiamart: "IndiaMART",
  justdial: "Justdial",
};

const PAYMENT_WORDS: Partial<Record<string, string>> = {
  razorpay: "online",
  cash: "cash",
  upi: "UPI",
  card: "card",
  bank_transfer: "bank transfer",
};

const SEGMENT_INFO: Partial<Record<string, { label: string; tone: string }>> = {
  A: { label: "Hot", tone: "text-[#b93815]" },
  B: { label: "Warm", tone: "text-[#b54708]" },
  C: { label: "Cold", tone: "text-[#175cd3]" },
  D: { label: "Not interested", tone: "text-[#64748b]" },
};

/** Phone header: the interest word as a chip, and the same tint behind the avatar. */
const PHONE_SEGMENT: Record<string, string> = {
  A: "bg-rose-100 text-rose-800",
  B: "bg-amber-100 text-amber-900",
  C: "bg-slate-200 text-slate-700",
  D: "bg-slate-100 text-slate-500",
};

function initialsOf(name: string | null | undefined, phone: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length > 0) return words.slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const digits = (phone ?? "").replace(/\D/g, "");
  return digits ? digits.slice(-2) : "?";
}

/** One of the four round-square actions under the phone header. */
function PhoneAction({
  label,
  icon: Icon,
  href,
  onClick,
  disabled,
  tone = "soft",
}: {
  label: string;
  icon: LucideIcon;
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "primary" | "soft" | "danger";
}) {
  const box = cn(
    "flex h-[52px] w-[52px] items-center justify-center rounded-2xl transition-colors",
    disabled
      ? "bg-slate-100 text-slate-400"
      : tone === "primary"
        ? "bg-primary text-white"
        : tone === "danger"
          ? "bg-rose-50 text-rose-700"
          : "bg-primary-light text-primary-900",
  );
  const wrap = "flex min-h-[44px] min-w-0 flex-col items-center gap-1.5 font-label text-[11px] font-bold text-ink";
  const inner = (
    <>
      <span className={box}>
        <Icon size={20} aria-hidden="true" />
      </span>
      <span className="max-w-full truncate">{label}</span>
    </>
  );
  if (disabled) {
    return (
      <span aria-disabled="true" className={cn(wrap, "opacity-70")}>
        {inner}
      </span>
    );
  }
  if (href) {
    return (
      <a href={href} className={wrap}>
        {inner}
      </a>
    );
  }
  return (
    <button type="button" onClick={onClick} className={wrap}>
      {inner}
    </button>
  );
}

const YEAR_OPTS: Intl.DateTimeFormatOptions = { year: "numeric", timeZone: "Asia/Kolkata" };

function sourceLabel(source: string | null | undefined): string {
  if (!source) return "";
  const known = SOURCE_LABELS[source];
  if (known) return known;
  if (source === "broadcast" || source === "upload" || source === "manual") return "a list you uploaded";
  return source.charAt(0).toUpperCase() + source.slice(1);
}

function channelLabel(channel: string | null | undefined): string {
  return sourceLabel(channel) || "WhatsApp";
}

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function dateLabel(iso: string): string {
  const d = new Date(iso);
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", timeZone: "Asia/Kolkata" };
  if (d.toLocaleDateString("en-IN", YEAR_OPTS) !== new Date().toLocaleDateString("en-IN", YEAR_OPTS)) {
    opts.year = "numeric";
  }
  return d.toLocaleDateString("en-IN", opts);
}

function monthYear(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function maskPhone(phone: string | null): string {
  if (!phone) return "";
  if (phone.length < 9) return `•• ••${phone.slice(-3)}`;
  return `${phone.slice(0, 5)}•• ••${phone.slice(-3)}`;
}

function joinParts(parts: (string | null | undefined | false)[]): string {
  return parts.filter((p): p is string => Boolean(p)).join(" · ");
}

const TONE = {
  green: "bg-[#ecfdf3] text-[#067647]",
  amber: "bg-[#fffaeb] text-[#b54708]",
  blue: "bg-[#eef4ff] text-[#3538cd]",
  teal: "bg-[#effaf8] text-[#0b7a6f]",
  orange: "bg-[#fef6ee] text-[#b93815]",
  violet: "bg-[#f4f3ff] text-[#5925dc]",
  red: "bg-[#fef3f2] text-[#b42318]",
  grey: "bg-[#f1f5f9] text-[#556274]",
};

interface DescribedEvent {
  icon: LucideIcon;
  tone: string;
  title: string;
  detail: string;
}

function describeEvent(e: AnyEvent): DescribedEvent {
  switch (e.kind) {
    case "order": {
      const amount = rupees(e.amount_paise);
      const items = e.items.length > 0 ? e.items.join(", ") : null;
      const common = [
        e.number ? `Order #${e.number}` : null,
        items,
        e.source === "walk_in" ? "in store" : null,
      ];
      if (e.stage === "won") {
        const method = e.payment_method ? PAYMENT_WORDS[e.payment_method] : undefined;
        return {
          icon: IndianRupee,
          tone: TONE.green,
          title: `Paid ${amount}${method ? ` · ${method}` : ""}`,
          detail: joinParts([...common, e.by ? `by ${e.by}` : null]),
        };
      }
      if (e.stage === "awaiting_payment") {
        return {
          icon: IndianRupee,
          tone: TONE.amber,
          title: `Waiting for payment · ${amount}`,
          detail: joinParts([...common, e.by ? `by ${e.by}` : null]),
        };
      }
      if (e.stage === "quoted") {
        return {
          icon: ShoppingBag,
          tone: TONE.blue,
          title: `Quote sent · ${amount}`,
          detail: joinParts([...common, e.by ? `by ${e.by}` : null]),
        };
      }
      return {
        icon: ShoppingBag,
        tone: TONE.grey,
        title: `Order lost · ${amount}`,
        detail: joinParts([...common, e.by ? `by ${e.by}` : null, e.lost_reason ? `"${e.lost_reason}"` : null]),
      };
    }
    case "booking": {
      // From the bookings table: service, staff, time and status. The older "booked a visit" event has only for/note.
      const b = e as BookingEventFields;
      const status = bookingStatusWords(b.status);
      const when = b.time ?? b.for;
      return {
        icon: CalendarCheck,
        tone: TONE.blue,
        title: b.service ? `Booking · ${b.service}${status && status !== "booked" ? ` · ${status}` : ""}` : "Booked a visit",
        detail: joinParts([when ? `For ${dateLabel(when)}` : null, b.staff ? `with ${b.staff}` : null, b.note]),
      };
    }
    case "refund": {
      const method = refundMethodWords(e.method);
      return {
        icon: RotateCcw,
        tone: TONE.amber,
        title: `Refund ${e.amount_paise != null ? rupees(e.amount_paise) : ""}${method ? ` · ${method}` : ""}`.trim(),
        detail: joinParts([e.number ? `Order #${e.number}` : null, e.by ? `by ${e.by}` : null]),
      };
    }
    case "visit":
      return {
        icon: CalendarCheck,
        tone: TONE.green,
        title: `Visited${e.service ? ` · ${e.service}` : ""}`,
        detail: joinParts([e.staff ? `with ${e.staff}` : null]),
      };
    case "no_show":
      return {
        icon: CalendarX,
        tone: TONE.red,
        title: `Didn't come${e.service ? ` · ${e.service}` : ""}`,
        detail: joinParts([e.staff ? `booked with ${e.staff}` : null]),
      };
    case "feedback":
      return {
        icon: Star,
        tone: e.stars != null && e.stars <= 3 ? TONE.red : TONE.green,
        title: `Rated ${starsText(e.stars)}`,
        detail: joinParts([e.reason ? `"${e.reason}"` : null, e.staff ? `with ${e.staff}` : null]),
      };
    case "chat": {
      const team = e.team;
      let detail: string;
      if (e.ai_replies > 0 && team.length > 0) detail = `AI agent and ${team.join(", ")} replied`;
      else if (e.ai_replies > 0) detail = "AI agent replied";
      else if (team.length > 0) detail = `${team.join(", ")} replied`;
      else if (e.outbound === 0) detail = "No reply yet";
      else detail = "Replied";
      return {
        icon: MessageCircle,
        tone: TONE.teal,
        title: `Chat on ${channelLabel(e.channel)} · ${plural(e.inbound + e.outbound, "message", "messages")}`,
        detail,
      };
    }
    case "call": {
      const words = e.outcome ? (e.outcome === "callback" ? "call back" : e.outcome.replace(/_/g, " ")) : null;
      let length: string | null = null;
      if (e.seconds !== null && e.seconds >= 60) length = `${Math.round(e.seconds / 60)} min`;
      else if (e.seconds !== null && e.seconds > 0) length = `${e.seconds} sec`;
      const notes = e.notes && e.notes.length > 80 ? `${e.notes.slice(0, 80)}…` : e.notes;
      return {
        icon: Phone,
        tone: TONE.orange,
        title: `Call${words ? ` · ${words}` : ""}`,
        detail: joinParts([e.by, length, e.reason ? `"${e.reason}"` : null, notes]),
      };
    }
    case "broadcast": {
      const status =
        e.status === "sent" ? "Sent"
          : e.status === "failed" ? "Didn't go"
            : e.status === "opted_out_skip" ? "Skipped: on Said stop"
              : e.status;
      return {
        icon: Megaphone,
        tone: TONE.violet,
        title: `Got broadcast "${e.name ?? "a campaign"}"`,
        detail: joinParts([status, e.reply ? `replied (${e.reply})` : null]),
      };
    }
    case "said_stop": {
      let detail: string;
      if (e.source === "stop_reply") detail = `Replied STOP${e.detail ? ` to ${e.detail}` : ""}`;
      else if (e.source === "chat_ai") detail = `Said no in chat${e.detail ? `: "${e.detail.slice(0, 60)}"` : ""}`;
      else if (e.source === "call") detail = `Asked on a call${e.detail ? ` with ${e.detail}` : ""}`;
      else if (e.source === "staff") detail = `Added by ${e.detail ?? "a team member"}`;
      else detail = "Before we tracked how";
      return { icon: BellOff, tone: TONE.red, title: "Said stop", detail };
    }
    case "joined":
      return {
        icon: UserPlus,
        tone: TONE.grey,
        title: "Became a customer",
        detail: joinParts([
          e.source ? `Came from ${sourceLabel(e.source)}` : null,
          e.ad ? `ad "${e.ad}"` : null,
        ]),
      };
  }
}

function channelPillTone(channel: string): string {
  if (channel === "whatsapp") return TONE.green;
  if (channel === "instagram") return "bg-[#fdf2fa] text-[#c11574]";
  return "bg-slate-100 text-slate-700";
}

function Pill({ className, children, href }: { className: string; children: ReactNode; href?: string }) {
  const base = "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold";
  if (href) {
    return (
      <Link href={href} className={cn(base, className, "hover:opacity-80")}>
        {children}
      </Link>
    );
  }
  return <span className={cn(base, className)}>{children}</span>;
}

export default function CustomerPage() {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("leads.manage");

  const routeParams = useParams<{ id: string }>();
  const leadId = routeParams?.id ?? null;
  const [profile, setProfile] = useState<ProfileX | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ChipKey>("all");
  const [stopDialog, setStopDialog] = useState<"add" | "remove" | null>(null);
  const [stopBusy, setStopBusy] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const [tagBusy, setTagBusy] = useState(false);

  const load = useCallback(async () => {
    if (!leadId) return;
    try {
      setProfile((await api.customerProfile.get(leadId)) as unknown as ProfileX);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Unknown error");
    }
  }, [leadId]);

  useEffect(() => {
    setProfile(null);
    setLoadError(null);
    void load();
  }, [load]);

  const timeline = useMemo(() => {
    if (!profile) return [];
    return profile.timeline.filter((e) => eventMatchesChip(e.kind, filter));
  }, [profile, filter]);

  async function changeSaidStop(action: "add" | "remove") {
    if (!leadId || !profile) return;
    const name = profile.lead.name || maskPhone(profile.lead.phone);
    setStopBusy(true);
    try {
      if (action === "add") {
        await api.saidStop.add([leadId]);
        toast.success(`${name} is on Said stop`);
      } else {
        await api.saidStop.remove([leadId]);
        toast.success(`${name} is off Said stop`);
      }
      setStopDialog(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update Said stop");
    } finally {
      setStopBusy(false);
    }
  }

  async function changeTags(kind: "add" | "remove", tags: string[]) {
    if (!leadId || tags.length === 0) return;
    setTagBusy(true);
    try {
      const result = kind === "add" ? await tagsApi.add([leadId], tags) : await tagsApi.remove([leadId], tags);
      if (kind === "add" && (result.skipped_limit ?? 0) > 0) toast.error(describeTagResult(kind, result));
      setTagInput("");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not change tags");
    } finally {
      setTagBusy(false);
    }
  }

  if (!profile && !loadError) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Loading customer">
        <div className="h-28 animate-pulse rounded-2xl bg-slate-100" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-100" />
          ))}
        </div>
        <div className="h-96 animate-pulse rounded-2xl bg-slate-100" />
      </div>
    );
  }

  if (!profile) {
    const notFound = loadError?.toLowerCase().includes("not found") ?? false;
    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-6 shadow-sm">
          <h1 className="font-display text-lg font-bold text-[#0A1528]">
            {notFound ? "Customer not found" : "We couldn’t open this customer."}
          </h1>
          <p className="mt-1 text-sm text-[#64748b]">
            {notFound ? "This customer was removed or isn't yours to see." : "Check your connection and try again."}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link
              href="/dashboard/leads"
              className="rounded-xl border border-[#e2e8f0] bg-white px-3.5 py-2 text-xs font-bold text-[#0A1528] hover:bg-slate-50"
            >
              Back to Customers
            </Link>
            <button
              type="button"
              onClick={() => {
                setLoadError(null);
                void load();
              }}
              className="rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white"
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  const { lead, totals, reached_on, said_stop } = profile;
  const displayName = lead.name || maskPhone(lead.phone) || "this customer";
  const firstName = lead.name?.trim().split(/\s+/)[0] || "this customer";
  const segment = lead.segment ? SEGMENT_INFO[lead.segment] : undefined;

  const subParts = [
    lead.created_at ? `Customer since ${monthYear(lead.created_at)}` : null,
    lead.phone ? maskPhone(lead.phone) : null,
    lead.source ? `came from ${sourceLabel(lead.source)}${lead.ad_name ? ` · ad "${lead.ad_name}"` : ""}` : null,
    lead.handled_by ? `handled by ${lead.handled_by}` : null,
  ];

  const chatDays = Object.entries(reached_on.chat_days).filter(([, n]) => n > 0);
  // The four new totals show only when the backend sends them.
  const t = profile.totals;
  const extraTotals = t && ("refunds_paise" in t || "visits" in t || "no_shows" in t || "avg_stars" in t) ? t : null;
  const tags = profile.tags ?? [];

  function jumpToTags() {
    const card = document.getElementById("customer-tags");
    card?.scrollIntoView({ behavior: "smooth", block: "center" });
    document.getElementById("customer-tag-input")?.focus({ preventScroll: true });
  }

  const segmentChip = lead.segment ? PHONE_SEGMENT[lead.segment] : undefined;
  const phoneSubParts = [
    lead.created_at ? `Customer since ${monthYear(lead.created_at)}` : null,
    lead.source ? `from ${sourceLabel(lead.source)}${lead.ad_name ? ` · ad "${lead.ad_name}"` : ""}` : null,
    lead.handled_by ? `handled by ${lead.handled_by}` : null,
  ];

  return (
    <div className="space-y-4">
      {/* Phone: a centred header with four big actions. Larger screens keep the header below. */}
      <header className="relative rounded-2xl border border-border bg-white px-4 pb-5 pt-4 text-center shadow-sm lg:hidden">
        <Link
          href="/dashboard/leads"
          className="absolute left-1 top-1 flex min-h-[44px] items-center px-3 font-label text-xs font-bold text-primary"
        >
          ‹ Customers
        </Link>
        <div
          aria-hidden="true"
          className={cn(
            "mx-auto mt-5 flex h-16 w-16 items-center justify-center rounded-full font-display text-xl font-bold",
            segmentChip ?? "bg-slate-100 text-slate-600",
          )}
        >
          {initialsOf(lead.name, lead.phone)}
        </div>
        <div className="mt-3 flex min-w-0 flex-wrap items-center justify-center gap-x-2 gap-y-1">
          <h1 className="min-w-0 break-words font-display text-xl font-bold text-ink">{displayName}</h1>
          {segment && segmentChip && (
            <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 font-label text-[11px] font-bold", segmentChip)}>
              {segment.label}
            </span>
          )}
        </div>
        {lead.phone && <p className="mt-1 break-words font-body text-sm text-ink-secondary">{maskPhone(lead.phone)}</p>}
        <p className="mt-1 break-words font-body text-xs text-ink-muted">{joinParts(phoneSubParts)}</p>
        {lead.score != null && (
          <p className="mt-3 inline-flex max-w-full items-center gap-2 rounded-full bg-surface-mid px-3 py-1.5 font-body text-xs text-ink-secondary">
            <span className="shrink-0 font-bold text-ink">Score {lead.score}</span>
            <span className="min-w-0 truncate">from their chats</span>
          </p>
        )}
        <div className="mt-4 grid grid-cols-4 gap-2">
          <PhoneAction
            label="Call"
            icon={Phone}
            tone="primary"
            href={lead.phone ? `tel:${lead.phone.replace(/[\s()-]/g, "")}` : undefined}
            disabled={!lead.phone}
          />
          <PhoneAction
            label="Chat"
            icon={MessageCircle}
            onClick={() => router.push(`/dashboard/conversations?lead=${lead.id}`)}
          />
          <PhoneAction label="Tags" icon={TagIcon} onClick={jumpToTags} />
          {canManage && !said_stop.on_list && (
            <PhoneAction label="Said stop" icon={BellOff} tone="danger" onClick={() => setStopDialog("add")} />
          )}
          {canManage && said_stop.on_list && (
            <PhoneAction label="Allow again" icon={RotateCcw} onClick={() => setStopDialog("remove")} />
          )}
          {!canManage && (
            <PhoneAction
              label="Notes"
              icon={Star}
              onClick={() => document.getElementById("customer-notes")?.scrollIntoView({ behavior: "smooth", block: "center" })}
            />
          )}
        </div>
      </header>

      <header className="hidden flex-wrap items-start justify-between gap-3 rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm lg:flex">
        <div className="min-w-0">
          <Link href="/dashboard/leads" className="text-xs font-bold text-primary hover:underline">
            ‹ Customers
          </Link>
          <h1 className="mt-1 break-words font-display text-xl font-bold text-[#0A1528]">{displayName}</h1>
          <p className="mt-1 break-words text-xs text-[#64748b]">{joinParts(subParts)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => router.push(`/dashboard/conversations?lead=${lead.id}`)}
            className="rounded-xl border border-[#e2e8f0] bg-white px-3.5 py-2 text-xs font-bold text-[#0A1528] hover:bg-slate-50"
          >
            Open chat
          </button>
          {canManage && !said_stop.on_list && (
            <button
              type="button"
              onClick={() => setStopDialog("add")}
              className="rounded-xl border border-[#fecdca] bg-white px-3.5 py-2 text-xs font-bold text-[#b42318] hover:bg-red-50"
            >
              Add to said stop
            </button>
          )}
          {canManage && said_stop.on_list && (
            <button
              type="button"
              onClick={() => setStopDialog("remove")}
              className="rounded-xl border border-[#e2e8f0] bg-white px-3.5 py-2 text-xs font-bold text-[#0A1528] hover:bg-slate-50"
            >
              Remove from said stop
            </button>
          )}
        </div>
      </header>

      <div className="grid grid-cols-3 gap-2 lg:hidden">
        <div className="min-w-0 rounded-2xl border border-border bg-white px-2.5 py-3 text-center shadow-sm">
          <div className="truncate font-label text-[11px] font-semibold text-ink-muted">Total spent</div>
          <div className="mt-1 truncate font-display text-base font-bold text-[#067647]">{rupees(totals.spent_paise)}</div>
          <div className="mt-0.5 truncate text-[11px] text-ink-muted">
            {totals.orders_won > 0 ? `avg ${rupees(totals.average_paise)}` : "nothing bought yet"}
          </div>
        </div>
        <div className="min-w-0 rounded-2xl border border-border bg-white px-2.5 py-3 text-center shadow-sm">
          <div className="truncate font-label text-[11px] font-semibold text-ink-muted">Bought</div>
          <div className="mt-1 truncate font-display text-base font-bold text-ink">
            {totals.orders_won === 0 ? "Not yet" : plural(totals.orders_won, "time", "times")}
          </div>
          <div className="mt-0.5 truncate text-[11px] text-ink-muted">
            {totals.last_bought_at ? `last ${dateLabel(totals.last_bought_at)}` : " "}
          </div>
        </div>
        <div className="min-w-0 rounded-2xl border border-border bg-white px-2.5 py-3 text-center shadow-sm">
          <div className="truncate font-label text-[11px] font-semibold text-ink-muted">Still to pay</div>
          <div className="mt-1 truncate font-display text-base font-bold text-ink">{rupees(totals.to_pay_paise)}</div>
          <div className="mt-0.5 truncate text-[11px] text-ink-muted">
            {totals.orders_waiting > 0 ? `${totals.orders_waiting} waiting` : "nothing pending"}
          </div>
        </div>
      </div>

      <div className="hidden grid-cols-2 gap-3 lg:grid lg:grid-cols-5">
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold text-[#64748b]">Total spent</div>
          <div className="mt-1 text-xl font-bold text-[#067647]">{rupees(totals.spent_paise)}</div>
          <div className="mt-1 text-xs text-[#64748b]">
            {totals.orders_won > 0 ? plural(totals.orders_won, "paid order", "paid orders") : "nothing bought yet"}
          </div>
        </div>
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold text-[#64748b]">Average bill</div>
          <div className="mt-1 text-xl font-bold text-[#0A1528]">
            {totals.orders_won > 0 ? rupees(totals.average_paise) : "—"}
          </div>
          <div className="mt-1 text-xs text-[#64748b]">across paid orders</div>
        </div>
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold text-[#64748b]">Bought</div>
          <div className="mt-1 text-xl font-bold text-[#0A1528]">
            {totals.orders_won === 0 ? "Not yet" : plural(totals.orders_won, "time", "times")}
          </div>
          <div className="mt-1 text-xs text-[#64748b]">
            {totals.last_bought_at ? `last on ${dateLabel(totals.last_bought_at)}` : " "}
          </div>
        </div>
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold text-[#64748b]">Interest now</div>
          <div className={cn("mt-1 text-xl font-bold", segment?.tone ?? "text-[#0A1528]")}>
            {segment?.label ?? "—"}
          </div>
          <div className="mt-1 text-xs text-[#64748b]">
            {lead.score != null ? `score ${lead.score} · from their chats` : " "}
          </div>
        </div>
        <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold text-[#64748b]">Still to pay</div>
          <div className="mt-1 text-xl font-bold text-[#0A1528]">{rupees(totals.to_pay_paise)}</div>
          <div className="mt-1 text-xs text-[#64748b]">
            {totals.orders_waiting > 0
              ? `${plural(totals.orders_waiting, "payment", "payments")} waiting`
              : "nothing pending"}
          </div>
        </div>
      </div>

      {extraTotals && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <div className="text-xs font-semibold text-[#556274]">Refunds</div>
            <div className="mt-1 text-xl font-bold text-[#0A1528]">{rupees(extraTotals.refunds_paise ?? 0)}</div>
            <div className="mt-1 text-xs text-[#556274]">given back</div>
          </div>
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <div className="text-xs font-semibold text-[#556274]">Visits</div>
            <div className="mt-1 text-xl font-bold text-[#0A1528]">{extraTotals.visits ?? 0}</div>
            <div className="mt-1 text-xs text-[#556274]">came to you</div>
          </div>
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <div className="text-xs font-semibold text-[#556274]">No-shows</div>
            <div className={cn("mt-1 text-xl font-bold", (extraTotals.no_shows ?? 0) > 0 ? "text-[#b42318]" : "text-[#0A1528]")}>
              {extraTotals.no_shows ?? 0}
            </div>
            <div className="mt-1 text-xs text-[#556274]">booked, didn&apos;t come</div>
          </div>
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <div className="text-xs font-semibold text-[#556274]">Average stars</div>
            <div className="mt-1 text-xl font-bold text-[#0A1528]">
              {extraTotals.avg_stars != null ? extraTotals.avg_stars.toFixed(1) : "—"}
            </div>
            <div className="mt-1 text-xs text-[#556274]">
              {extraTotals.avg_stars != null ? "from their ratings" : "not rated yet"}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <section className="min-w-0 flex-1 rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-2">
            <div>
              <h2 className="inline text-base font-bold text-[#0A1528]">Everything with {firstName}</h2>{" "}
              <span className="text-xs text-[#64748b]">newest first</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {TIMELINE_CHIPS.map((chip) => {
                const active = filter === chip.key;
                return (
                  <button
                    key={chip.key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setFilter(chip.key)}
                    className={cn(
                      "rounded-full px-2.5 py-1 text-xs font-semibold max-lg:min-h-11 max-lg:px-3.5",
                      active ? "bg-primary text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200",
                    )}
                  >
                    {chip.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-2">
            {timeline.length === 0 ? (
              <p className="py-8 text-center text-sm text-[#64748b]">Nothing here yet.</p>
            ) : (
              timeline.map((e, i) => {
                const described = describeEvent(e);
                const Icon = described.icon;
                return (
                  <div
                    key={`${e.kind}-${e.at}-${i}`}
                    className="flex gap-3 border-b border-[#eef2f6] py-3.5 last:border-b-0"
                  >
                    <div
                      className={cn(
                        "flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-xl",
                        described.tone,
                      )}
                      aria-hidden="true"
                    >
                      <Icon size={16} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="break-words text-sm font-semibold text-[#0A1528]">{described.title}</div>
                      {described.detail && (
                        <div className="mt-0.5 break-words text-xs text-[#64748b]">{described.detail}</div>
                      )}
                    </div>
                    <div className="shrink-0 whitespace-nowrap pl-2 text-xs text-[#64748b]">{dateLabel(e.at)}</div>
                  </div>
                );
              })
            )}
          </div>
        </section>

        <aside className="flex flex-col gap-3 xl:w-[380px] xl:shrink-0">
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <h2 className="text-sm font-bold text-[#0A1528]">Reached on</h2>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {chatDays.map(([channel, n]) => (
                <Pill key={channel} className={channelPillTone(channel)}>
                  {`${channelLabel(channel)} · ${plural(n, "chat day", "chat days")}`}
                </Pill>
              ))}
              {reached_on.calls > 0 && (
                <Pill className="bg-slate-100 text-slate-700">{`Calls · ${reached_on.calls}`}</Pill>
              )}
              {reached_on.broadcasts > 0 && (
                <Pill className="bg-slate-100 text-slate-700">{`Broadcasts · ${reached_on.broadcasts}`}</Pill>
              )}
              {reached_on.store_bills > 0 && (
                <Pill className="bg-slate-100 text-slate-700">
                  {`Store · ${plural(reached_on.store_bills, "bill", "bills")}`}
                </Pill>
              )}
              {chatDays.length === 0 &&
                reached_on.calls === 0 &&
                reached_on.broadcasts === 0 &&
                reached_on.store_bills === 0 && (
                  <p className="text-xs text-[#64748b]">Not reached yet</p>
                )}
            </div>
          </div>

          <div id="customer-tags" className="scroll-mt-4 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <h2 className="text-sm font-bold text-[#0A1528]">Tags</h2>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {tags.length === 0 && <p className="text-xs text-[#556274]">No tags yet</p>}
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 rounded-full bg-slate-100 py-1 pl-2.5 pr-1.5 text-xs font-semibold text-slate-700"
                >
                  <Link href={`/dashboard/leads?tab=people&tag=${encodeURIComponent(tag)}`} className="hover:text-primary">
                    {tag}
                  </Link>
                  {canManage && (
                    <button
                      type="button"
                      onClick={() => void changeTags("remove", [tag])}
                      disabled={tagBusy}
                      aria-label={`Remove tag ${tag}`}
                      className="relative rounded-full p-0.5 hover:bg-slate-200 disabled:opacity-50 max-lg:before:absolute max-lg:before:-inset-3 max-lg:before:content-['']"
                    >
                      <X size={12} />
                    </button>
                  )}
                </span>
              ))}
            </div>
            {canManage && tags.length < MAX_TAGS_PER_PERSON && (
              <form
                className="mt-3 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void changeTags("add", parseTagInput(tagInput));
                }}
              >
                <input
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  maxLength={120}
                  placeholder="Add a tag, e.g. VIP"
                  aria-label="Add a tag"
                  id="customer-tag-input"
                  className="min-w-0 flex-1 rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 text-xs max-lg:min-h-11 max-lg:text-base text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <button
                  type="submit"
                  disabled={tagBusy || !cleanTag(tagInput)}
                  className="flex shrink-0 items-center gap-1 rounded-lg bg-primary px-2.5 py-1.5 text-xs font-bold text-white disabled:opacity-40 max-lg:min-h-11 max-lg:px-4"
                >
                  <Plus size={12} aria-hidden="true" /> Add
                </button>
              </form>
            )}
            {canManage && tags.length >= MAX_TAGS_PER_PERSON && (
              <p className="mt-2 text-xs text-[#556274]">{MAX_TAGS_PER_PERSON} tags is the most one person can have.</p>
            )}
          </div>

          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <h2 className="text-sm font-bold text-[#0A1528]">Interested in</h2>
            <div className="mt-2.5">
              <InterestedIn leadId={leadId ?? profile.lead.id} />
            </div>
          </div>

          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <h2 className="text-sm font-bold text-[#0A1528]">Groups</h2>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {profile.groups.length === 0 && <p className="text-xs text-[#64748b]">Not in any group</p>}
              {profile.groups.map((g) => (
                <Pill
                  key={g.id}
                  href={`/dashboard/leads?tab=people&group_id=${g.id}`}
                  className="bg-slate-100 text-slate-700"
                >
                  {g.kind === "rule" && <RefreshCw size={11} aria-hidden="true" />}
                  {g.name}
                </Pill>
              ))}
            </div>
          </div>

          <div id="customer-notes" className="scroll-mt-4 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <h2 className="text-sm font-bold text-[#0A1528]">Team notes</h2>
            {profile.notes.length === 0 ? (
              <p className="mt-2.5 text-xs text-[#64748b]">No notes yet. Notes added in Chats show here.</p>
            ) : (
              <ul className="mt-2.5 space-y-3">
                {profile.notes.slice(0, 5).map((n) => (
                  <li key={n.id}>
                    <p className="line-clamp-4 whitespace-pre-line break-words text-sm text-[#0A1528]">
                      {n.content ?? ""}
                    </p>
                    <p className="mt-0.5 text-xs text-[#64748b]">
                      {`${n.by ?? "Team"} · ${dateLabel(n.created_at)}`}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[#0A1528]">Messages and calls</div>
              <div className="text-xs text-[#64748b]">
                {said_stop.on_list
                  ? "No offers, follow-ups or calls go to them"
                  : said_stop.do_not_call
                    ? "Messages allowed, no calls"
                    : "Not on Said stop"}
              </div>
            </div>
            {said_stop.on_list ? (
              <Pill className={TONE.red}>On Said stop</Pill>
            ) : said_stop.do_not_call ? (
              <Pill className={TONE.amber}>Do not call</Pill>
            ) : (
              <Pill className={TONE.green}>Allowed</Pill>
            )}
          </div>

          <p className="px-1 text-xs text-[#64748b]">
            One customer = one phone number. Chats, orders and calls from every channel join here.
          </p>
        </aside>
      </div>

      {canManage && (
        <>
          <ConfirmModal
            open={stopDialog === "add"}
            onClose={() => setStopDialog(null)}
            onConfirm={() => void changeSaidStop("add")}
            title={`Add ${displayName} to Said stop?`}
            description="Offers, follow-ups, auto-messages and telecaller calls stop for them. The AI agent still answers if they message you, and payment messages still go."
            tone="danger"
            confirmLabel="Add to said stop"
            loading={stopBusy}
            loadingLabel="Adding…"
          />
          <ConfirmModal
            open={stopDialog === "remove"}
            onClose={() => setStopDialog(null)}
            onConfirm={() => void changeSaidStop("remove")}
            title={`Remove ${displayName} from Said stop?`}
            description="Only do this if the customer asked to hear from you again."
            tone="primary"
            confirmLabel="Remove from said stop"
            loading={stopBusy}
            loadingLabel="Removing…"
          />
        </>
      )}
    </div>
  );
}
