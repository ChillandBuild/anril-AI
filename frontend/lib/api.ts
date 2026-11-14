import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://aira-ai-5tfr.onrender.com";
const MAX_LEADS_LIST_LIMIT = 200;

export async function getAuthHeaders(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) return {};
  return { Authorization: `Bearer ${session.access_token}` };
}

export interface Lead {
  id: string;
  phone: string | null;
  name: string | null;
  source: string;
  score: number;
  segment: "A" | "B" | "C" | "D";
  ai_enabled: boolean;
  opted_out: boolean;
  converted_at?: string | null;
  assigned_to?: string | null;
  needs_human_intervention?: boolean;
  tg_username?: string | null;
  ig_user_id?: string | null;
  fb_user_id?: string | null;
  ad_campaign_id?: string | null;
  created_at: string;
  last_message_content?: string | null;
  /** Who sent the last message (inbox rows); null when unknown. */
  last_message_direction?: "inbound" | "outbound" | null;
  last_message_is_ai?: boolean | null;
  pinned_at?: string | null;
  last_inbound_at?: string | null;
  broadcast_sent_at?: string | null;
  assigned_at?: string | null;
  broadcast_id?: string | null;
  template_name?: string | null;
  tag_name?: string | null;
  ad_campaign_name?: string | null;
  channel?: string | null;
  call_status?: LeadCallStatus | null;
  do_not_call?: boolean;
  needs_human_attention?: boolean;
  archived_at?: string | null;
  blocked_at?: string | null;
}

export interface CatalogVariantGroup {
  id: string;
  tenant_id: string;
  name: string;
  item_type: string;
  created_at: string;
}

export interface CatalogItem {
  id: string;
  tenant_id: string;
  name: string;
  item_type: string;
  description: string | null;
  status: "draft" | "ready";
  created_at: string;
  updated_at: string;
  attributes: Record<string, string>;
  variant_group_id: string | null;
  embedding: string | null;
  price_paise: number | null;
  price_note: string | null;
  stock_quantity: number | null;
  gst_rate: number | null;
  held_quantity?: number;
  thumbnail_url?: string | null;
}

export interface CatalogMedia {
  id: string;
  tenant_id: string;
  catalog_item_id: string;
  storage_path: string;
  label: string | null;
  sort_order: number;
  created_at: string;
  item_name?: string | null;
  url?: string;
}

export interface CatalogAiRules {
  can_recommend: boolean;
  can_send_images: boolean;
  max_images_per_reply: number;
  // Operator-set controls, read-only from the client side -- not part of the PATCH payload.
  feature_enabled: boolean;
  max_images_ceiling: number;
}

export interface Message {
  id: string;
  lead_id: string;
  direction: "inbound" | "outbound";
  channel: string;
  content: string;
  is_ai_generated: boolean;
  reply_source?: "knowledge" | "ai" | null;
  meta_message_id?: string | null;
  media_url?: string | null;
  media_type?: "image" | "document" | "audio" | "video" | "sticker" | null;
  media_filename?: string | null;
  media_mime_type?: string | null;
  created_at: string;
}

export interface Caller {
  id: string;
  name: string;
  phone: string | null;
  active: boolean;
  status?: "active" | "break" | "logged_out";
  status_changed_at?: string;
  target?: number;
  telecmi_agent_id?: string | null;
  has_telecmi_agent_password?: boolean;
  shift_start_hour?: number | null;
  shift_end_hour?: number | null;
}

/** Daily/monthly winner: 70% average score + 30% volume (calls vs the busiest telecaller). */
export interface Winner {
  caller_id: string;
  name: string;
  points: number;
  avg_score: number;
  total_calls: number;
  scored_calls: number;
  volume_points: number;
  min_scored_calls: number;
}

export interface CallerStats {
  calls_today: number;
  calls_this_week: number;
  conversion_rate_week: number;
  avg_duration_seconds: number | null;
  pending_hot_leads: number;
  /** Average of this IST month's scored calls; null until one is scored.
   *  Absent entirely for SIM clients -- they get no evaluation at all. */
  avg_score_month?: number | null;
  scored_calls_month?: number;
  total_calls_month: number;
  name: string;
  phone: string;
  status: string;
  caller_id: string;
}

/** Wrap-up v2 tap 1 (call_logs.manual_status). */
export type CallConnect = "connected" | "not_picked" | "busy" | "switched_off";
export type NoConnect = Exclude<CallConnect, "connected">;
/** Wrap-up v2 tap 2 (call_logs.outcome). */
export type CallResult =
  | "interested_booked" | "interested_needs_time" | "maybe_later" | "call_later" | "converted"
  | "not_interested" | "disqualified" | "wrong_number" | "language_barrier" | "do_not_call";
export type LeadCallStatus =
  | "new" | "trying" | "unreachable" | "hot" | "warm" | "cold" | "callback" | "converted"
  | "not_interested" | "disqualified" | "wrong_number" | "language_barrier" | "dnc";
export type OutcomeReason =
  | "price" | "already_bought" | "no_need" | "other" | "never_enquired" | "not_a_fit" | "not_decision_maker";
export type PreferredLanguage = "tamil" | "english" | "hindi" | "telugu" | "malayalam" | "kannada" | "other";
export type CallTemperature = "hot" | "warm" | "cold";

export interface WrapupPayload {
  manual_status: CallConnect;
  outcome: CallResult | null;
  notes: string | null;
  next_action_at: string | null;
  reason: OutcomeReason | null;
  preferred_language: PreferredLanguage | null;
  stop_messages: boolean;
  products: { catalog_item_id: string; qty: number }[];
  amount_paise: number | null;
  duration_seconds?: number;
  manual_started_at?: string;
  manual_ended_at?: string;
}

export interface WrapupContext {
  connect_prefill: CallConnect | null;
  never_connected: boolean;
  failed_before: number;
  retry_suggestions: Record<NoConnect, string>;
}

export interface WrapupSaved {
  call_log_id: string;
  manual_status: CallConnect;
  outcome: CallResult | null;
  call_status: LeadCallStatus | null;
  next_action_at: string | null;
  deal_id: string | null;
  score: number | null;
  score_status: CallScoreStatus | null;
}

export interface SendDetailsVariable {
  key: string;
  role: "customer_name" | "business_name" | "details" | "next_step" | null;
  value: string;
}

export interface SendDetailsTemplate {
  id: string;
  name: string;
  language: string;
  body_text: string;
  variables: SendDetailsVariable[];
}

/** A template waiting to go out (or one that was not sent, kept visible for two days). */
export interface ScheduledTemplate {
  id: string;
  lead_id: string;
  template_name: string;
  /** The text as the customer will see it. */
  content: string;
  /** UTC ISO time. */
  send_at: string;
  status: "scheduled" | "sending" | "sent" | "failed" | "skipped" | "cancelled";
  /** Plain-words reason when it was not sent. */
  reason: string | null;
  created_at: string;
}

export type ScheduledOverviewStatus = "scheduled" | "sending" | "sent" | "failed" | "skipped" | "cancelled";

/** One template scheduled for one lead, as the Scheduled templates page lists it. */
export interface ScheduledOverviewTemplate {
  id: string;
  lead_id: string;
  lead_name: string | null;
  lead_phone: string | null;
  lead_source: string | null;
  template_name: string;
  /** The text as the customer will see it. */
  content: string;
  /** UTC ISO time. */
  send_at: string;
  status: ScheduledOverviewStatus;
  reason: string | null;
  created_by_name: string;
  /** Messages scheduled together from Segments share one batch. Null for a single message. */
  batch_id: string | null;
  batch_label: string | null;
}

/** A broadcast waiting in Outbound Leads (scheduled once, or a drip). */
export interface ScheduledOverviewBroadcast {
  id: string;
  ids: string[];
  kind: "scheduled" | "drip";
  template_name: string;
  /** UTC ISO time of the first send. */
  send_at: string;
  status: "scheduled" | "sending" | "sent" | "failed" | "cancelled";
  recipients: number;
  days: number;
  file_name: string | null;
  has_file: boolean;
  created_by_name: string;
  error: string | null;
}

export interface ScheduledOverview {
  templates: ScheduledOverviewTemplate[];
  broadcasts: ScheduledOverviewBroadcast[];
  can_change_templates: boolean;
  can_change_broadcasts: boolean;
}

export interface ScheduledBulkRequest {
  action: "cancel" | "restore" | "reschedule";
  template_ids: string[];
  broadcast_ids: string[];
  /** UTC ISO time. Required for "reschedule". */
  send_at?: string;
}

export interface ScheduledBulkResult {
  done: number;
  failed: { kind: "template" | "broadcast"; id: string; reason: string }[];
}

export type SendDetailsContext =
  | { available: false }
  | { available: true; window_open: boolean; last_inbound_at: string | null; free_text: string; templates: SendDetailsTemplate[] };

export interface TemplatePerformanceRow {
  template_name: string;
  broadcasts: number;
  sent: number;
  read: number;
  replied: number;
  hot_leads: number;
  last_sent: string | null;
}

export type CallGroup = "not_connected" | "very_short" | "early_exit" | "real_conversation";
export type CheckKey =
  | "opening" | "courtesy" | "questions" | "listening" | "product_info"
  | "doubts" | "clarity" | "next_step" | "decision" | "crm_update";
export type CheckLevel = "excellent" | "good" | "partial" | "poor" | "missing";

export interface CallCheck {
  key: CheckKey;
  full: number;
  level: CheckLevel | null;
  ai_level: CheckLevel | null;
  capped_by: "talk_share" | "interruptions" | "talk_share_and_interruptions" | "wrong_info" | "rude" | null;
  marks: number | null;
  reason: string | null;
  quote: string | null;
  time: string | null;
  proof_missing: boolean;
}

export interface CallSign { sign: number; speaker: "telecaller" | "customer"; quote: string; time: string }

export interface EarlyExitCheck {
  polite: boolean;
  rude_quote: string | null;
  enquiry_confirmed_early: boolean;
  expected_crm: "wrong_number" | "not_enquired" | "callback" | "language_barrier" | "voicemail" | "other";
  crm_matches: boolean | null;
  no_wrapup?: boolean;
}

export type ReportMood = "positive" | "neutral" | "negative";
export type ReportHandling = "handled" | "partly" | "dodged";
export type ReportDirection = "warmed" | "cooled";

/** Every report moment: `time` is the label ("02:40"), `start` the seconds to seek to. */
export interface ReportMoment {
  time: string;
  start: number;
  quote: string;
}
export interface ReportMoodPoint extends ReportMoment { mood: ReportMood }
export interface ReportTurningPoint extends ReportMoment { direction: ReportDirection; why: string }
export interface ReportObjection extends ReportMoment { handling: ReportHandling; why: string }
export interface ReportPromise extends ReportMoment { risky: boolean; why: string }
export interface ReportCoach extends ReportMoment { tip: string }
export type SpeechSegments = [number, number][];

/** Call Report v1. Manager review route only; every key is optional. */
export interface CallReport {
  report_version?: number;
  mood?: ReportMoodPoint[];
  turning_point?: ReportTurningPoint | null;
  objections?: ReportObjection[];
  promises?: ReportPromise[];
  coach?: ReportCoach | null;
  talk?: { longest_monologue_s?: number | null; dead_air_s?: number | null } | null;
  segments?: { telecaller?: SpeechSegments; customer?: SpeechSegments } | null;
}

/** v4 evaluation (CallIQ Steps 1-2). Older rows have no evaluation_version 4 and are not shown. */
export interface CallEvaluation {
  evaluation_version: number;
  rules_version?: string;
  group?: "early_exit" | "real_conversation";
  signs?: CallSign[];
  valid_sign_count?: number;
  early_exit_check?: EarlyExitCheck;
  checks?: CallCheck[];
  top_improve?: CheckKey[];
  tips?: string[];
  wrong_info?: { quote: string; time: string; kb_fact: string | null }[];
  unverified_claims?: string[];
  language_barrier?: boolean;
  /** D10: the AI's Hot/Warm/Cold reading replaced the telecaller's. */
  crm_correction?: { from: CallTemperature; to: CallTemperature } | null;
  /** Manager review route only. */
  report?: CallReport;
}

export type CallAiStatus = "pending" | "transcribing" | "scoring" | "done" | "failed";
export type CallScoreStatus =
  | "processing" | "not_connected" | "very_short" | "early_exit" | "provisional" | "scored" | "failed";

export type CallAlertType =
  | "rude" | "wrong_info" | "crm_mismatch" | "no_proof" | "transcript_failed"
  | "language_barrier" | "lead_source_quality" | "tracks_swapped";

export interface CallAlert {
  id: string;
  type: CallAlertType;
  quote: string | null;
  detail: Record<string, unknown>;
  created_at: string;
  seen_at: string | null;
  caller_id: string | null;
  call_log_id: string | null;
  callers: { name: string | null } | null;
  call_logs: {
    id: string; created_at: string; duration_seconds: number | null; lead_id: string | null;
    leads: { name: string | null; phone: string | null } | null;
  } | null;
}

/** The full transcript never leaves the backend: only its first and last line. */
export interface TranscriptPreview {
  first: string;
  last: string | null;
  hidden_lines: number;
}

export interface PendingWrapupSummary {
  caller_id: string;
  name: string | null;
  pending_count: number;
  last_sync_at: string | null;
  has_sync_token: boolean;
  /** Aira Sync build the phone last reported; null = never reported (1.2 or older). */
  app_version: number | null;
  /** Newest published build from version.json; null if it couldn't be read. */
  latest_app_version: number | null;
}

export interface ReviewRange {
  start: string;
  end: string;
  callerId?: string | null;
}

function reviewQuery({ start, end, callerId }: ReviewRange): string {
  const qs = new URLSearchParams({ start, end });
  if (callerId) qs.set("caller_id", callerId);
  return qs.toString();
}

/** One lead in Call Review, with the telecaller's call and note totals for the range. */
export interface ReviewLead {
  id: string;
  name: string | null;
  phone: string | null;
  segment: "A" | "B" | "C" | "D" | null;
  assigned_to: string | null;
  assigned: boolean;
  calls: number;
  connected: number;
  talk_seconds: number;
  scored: number;
  score_sum: number;
  avg_score: number | null;
  early_exits: number;
  needs_review: boolean;
  notes: number;
  last_call_at: string | null;
  last_call: Pick<CallLog, "score" | "score_status" | "call_group" | "provider"> | null;
  last_activity_at: string | null;
}

export interface CallLog {
  id: string;
  lead_id: string | null;
  call_sid: string | null;
  duration_seconds: number | null;
  outcome: CallResult | null;
  disposition: string | null;
  manual_status?: CallConnect | null;
  recording_url: string | null;
  /** Absent entirely for SIM clients -- they get no evaluation at all. */
  score?: number | null;
  status: string;
  ai_summary: {
    course?: string;
    product?: string;
    budget?: string;
    timeline?: string;
    next_action?: string;
    sentiment?: string;
    brief?: string;
    objections?: string | string[];
    commitments?: string | string[];
    open_questions?: string | string[];
  } | null;
  /** Absent entirely for SIM clients -- they get no evaluation at all. */
  evaluation?: CallEvaluation | null;
  notes?: string | null;
  provider?: "telecmi" | "sim_basic";
  score_status?: CallScoreStatus | null;
  ai_status?: CallAiStatus | null;
  ai_error?: string | null;
  call_group?: CallGroup | null;
  talk_share?: number | null;
  interruption_count?: number | null;
  interruptions_per_5min?: number | null;
  score_final?: boolean;
  feedback_source?: "automatic" | "manual";
  manual_started_at?: string | null;
  manual_ended_at?: string | null;
  transcript_preview?: TranscriptPreview | null;
  direction?: "outgoing" | "incoming" | "missed" | null;
  feedback_at?: string | null;
  next_action_at?: string | null;
  outcome_reason?: OutcomeReason | null;
  preferred_language?: PreferredLanguage | null;
  ai_call_status?: CallTemperature | "none" | null;
  created_at: string;
  leads?: { phone: string | null; name: string | null } | null;
  callers?: { name: string | null } | null;
  caller_id?: string | null;
}

export interface NoteWithLead {
  id: string;
  lead_id: string;
  caller_id: string | null;
  call_log_id: string | null;
  content: string;
  structured: {
    course?: string;
    product?: string;
    budget?: string;
    timeline?: string;
    next_action?: string;
    sentiment?: string;
    brief?: string;
  };
  is_pinned: boolean;
  tags?: string[];
  created_at: string;
  leads: { id: string; name: string | null; phone: string; segment: string; score: number; assigned_to: string | null } | null;
}

export interface SegmentTemplate {
  id: string;
  segment: "A" | "B" | "C" | "D";
  message: string;
  enabled: boolean;
  updated_at: string;
}

export interface BroadcastHistoryItem {
  timestamp: string;
  broadcast_id?: string;
  template_name: string;
  opt_in_source: string;
  sent: number;
  delivered: number;
  opened: number;
  failed: number;
  total_leads: number;
  number_used: string;
  csv_file_url?: string;
  csv_file_path?: string;
  csv_file_name?: string;
  tag_id?: string;
  tag_name?: string;
  hot?: number;
  warm?: number;
  cold?: number;
  replied_positive?: number;
  replied_negative?: number;
  replied_neutral?: number;
}

export interface BroadcastResult {
  total: number;
  sent: number;
  failed: number;
  skipped_window: number;
}

export interface MarketplaceStatus {
  connected: boolean;
  last_lead_at: string | null;
  leads_this_month: number;
}

/** An event key: one of the built-ins (interested, signed_up, purchased) or a tenant's own custom key. */
export type AutoMessageEvent = string;
export type AutoMessageVarSource =
  | "first_name" | "full_name" | "page_url" | "phone" | "extra" | "text";

export interface AutoMessageVariable {
  source: AutoMessageVarSource;
  key?: string | null;
  value?: string | null;
  fallback?: string | null;
}

/** A rule as stored (what POST / PATCH return). */
export interface AutoMessageRuleRow {
  id: string;
  event: AutoMessageEvent;
  template_id: string;
  variables: AutoMessageVariable[];
  button_param: AutoMessageVariable | null;
  enabled: boolean;
  created_at: string;
}

/** A rule as GET /rules returns it: the stored row plus two computed flags. */
export interface AutoMessageRule extends AutoMessageRuleRow {
  /** At least one message for this event has gone out. */
  has_sent: boolean;
  /** The rule's template is still APPROVED by Meta. */
  template_approved: boolean;
}

export interface AutoMessageBuiltinEvent {
  key: string;
  label: string;
  description: string;
}

export interface AutoMessageCustomEvent {
  id: string;
  key: string;
  label: string;
  description: string | null;
  created_at: string;
}

export interface AutoMessageEvents {
  builtin: AutoMessageBuiltinEvent[];
  custom: AutoMessageCustomEvent[];
  /** Most custom events a tenant may have. */
  limit: number;
}

export interface AutoMessageSetup {
  ingest_url: string | null;
  form_script_url: string | null;
  /** The tenant sends from its own server, so the hosted website form is off. */
  private_send_on: boolean;
}

export interface AutoMessageSummary {
  sent: number;
  failed: number;
  skipped: number;
}

export interface AutoMessageSendsPage {
  sends: AutoMessageSend[];
  has_more: boolean;
}

export interface AutoMessagePreviewResult {
  status: "sent" | "failed";
  reason: string | null;
}

export interface AutoMessageTemplate {
  id: string;
  name: string;
  category: string | null;
  language: string | null;
  body_text: string;
  header_media_type: string | null;
  variable_count: number;
  has_dynamic_button: boolean;
  buttons: string[];
}

export interface PrivateSendDay {
  day: string;
  event: string;
  template_id: string | null;
  template_name: string | null;
  sent: number;
  failed: number;
}

export interface PrivateSendStatus {
  enabled: boolean;
  key_prefix: string | null;
  reply_mode: "client" | "aira" | null;
  days: PrivateSendDay[];
}

export interface AutoMessageSend {
  id: string;
  lead_id: string | null;
  phone: string;
  name: string | null;
  /** null when an app sent a template ID directly (source "partner"). */
  event: AutoMessageEvent | null;
  source: "website" | "api" | "store" | "partner";
  template_name: string | null;
  status: "queued" | "sending" | "sent" | "failed" | "skipped";
  reason: string | null;
  send_at: string;
  sent_at: string | null;
  created_at: string;
}

/** The Segments table's filters; a broadcast reaches exactly the leads they match. */
export interface BroadcastFilters {
  segment?: string;
  search?: string;
  source_filter?: string;
  ad_campaign_id?: string;
  broadcast_id?: string;
  date_from?: string;
  date_to?: string;
  assigned_to?: string;
  reply_window?: "open" | "closed";
}

export interface BroadcastPreview {
  matching: number;
  reachable: number;
  outside_window: number;
  no_opt_in: number;
}

export interface WabaTemplate {
  id: string;
  name: string;
  category: string;
  status: string;
  body_text?: string | null;
}

export interface ReengagementStep {
  id: string;
  tenant_id: string;
  type: "broadcast" | "inbound";
  broadcast_id?: string | null;
  delay_hours: number;
  target_segments: string[];
  target_sources?: string[] | null;
  message_type: "freeform" | "template";
  message_content?: string | null;
  template_name?: string | null;
  template_variables?: string[] | null;
  fallback_template_name?: string | null;
  fallback_template_variables?: string[] | null;
  created_at: string;
}

export interface ReengagementLog {
  id: string;
  step_id: string;
  lead_id: string;
  status: "sent" | "sent_fallback" | "skipped_window" | "failed";
  sent_at: string;
  leads?: { name: string | null; phone: string; segment: string | null } | null;
}

export interface KnowledgeReadinessItem {
  key: "about" | "how_to_buy" | "prices" | "handover" | "who" | "never" | "questions" | "voice";
  label: string;
  level: "must" | "nice" | "optional";
  ok: boolean;
}

export interface KnowledgeDocContent {
  id: string;
  name: string;
  file_type: string;
  size_bytes: number;
  status: string;
  created_at: string;
  /** What Aira looks up from this file: its facts once sorted, the whole text before. */
  full_text: string;
  /** False for documents uploaded before the original file was kept — text only. */
  downloadable: boolean;
  /** False for legacy files that were never sorted (Aira still reads all of them). */
  sorted: boolean;
  sort_state: "sorting" | "review" | "failed" | null;
}

// ─── Knowledge Auto-Sort ─────────────────────────────────────────────────────

export interface KnowledgeHunk {
  id: string;
  kind: "add" | "change" | "remove";
  /** Index into splitLines(base_description) where old_lines begin. */
  start: number;
  old_lines: string[];
  new_lines: string[];
  /** The hunk edits a line the client wrote — unticked by default. */
  touches_client_lines: boolean;
}

export interface KnowledgeConflict {
  id: string;
  topic: string;
  heading: string;
  option_a: string;
  source_a: string;
  option_b: string;
  source_b: string;
}

export interface KnowledgeFactDisagreement {
  id: string;
  where: "description" | "file";
  topic: string;
  new_value: string;
  existing_value: string;
  document_name: string | null;
  existing_line: string | null;
  proposed_line: string | null;
  client_line: boolean;
}

export interface KnowledgeReview {
  review_id: string;
  document_id: string;
  document_name: string;
  origin: "upload" | "resort";
  stale: boolean;
  base_version_id: string;
  base_description: string;
  proposed_description: string;
  hunks: KnowledgeHunk[];
  conflicts: KnowledgeConflict[];
  fact_disagreements: KnowledgeFactDisagreement[];
  facts: string;
  unverified: string[];
  left_out: { text: string; note: string }[];
  left_out_rules: string[];
  truncated: boolean;
  replaces_document: { id: string; name: string } | null;
  word_count: number;
  soft_word_limit: number;
  /** A sentence the upload contained telling customers how to reach a person
   *  (e.g. "Call Priya at 98765 43210"). "" when none was found. Never saved
   *  automatically -- the client chooses to use it as their handover line. */
  suggested_handover: string;
}

export type KnowledgeConflictChoice = "a" | "b" | "none";

export interface KnowledgeApplyChoices {
  base_version_id: string;
  accepted_hunk_ids: string[];
  conflict_choices: Record<string, KnowledgeConflictChoice>;
  accepted_update_ids: string[];
}

export type KnowledgeVersionReason =
  | "baseline"
  | "edit"
  | "upload"
  | "delete_document"
  | "resort"
  | "restore";

export interface KnowledgeVersion {
  id: string;
  kind: "description" | "facts";
  document_id: string | null;
  content: string;
  reason: KnowledgeVersionReason;
  created_by: string | null;
  created_at: string;
}

export interface KnowledgeDeletePreview {
  base_version_id: string;
  document_name: string;
  chunk_count: number;
  has_facts: boolean;
  remove_lines: string[];
  edited_lines: { original: string; current: string }[];
  description_will_change: boolean;
}

export interface SystemStatus {
  has_meta: boolean;
  has_gemini: boolean;
  has_groq: boolean;
  supabase_url: string;
}

export interface AnalyticsOverview {
  daily_leads: { day: string; count: number }[];
  daily_leads_trend_pct: number | null;
  /** Older leads brought back by an ad, per day. Optional so a frontend
   *  deployed ahead of the backend renders Fresh-only instead of crashing. */
  returning_ad_leads_daily?: { day: string; count: number }[];
  daily_messages: { day: string; inbound: number; outbound: number; ai: number; human: number }[];
  funnel: { inquiries: number; engaged: number; hot: number; converted: number };
  ai_vs_human: { ai: number; human: number };
  unreplied_24h: number;
  converted_7d: number;
  converted_7d_trend_pct: number | null;
  converted_today: number;
  ai_handled_today: number;
  by_segment: Record<"A" | "B" | "C" | "D", number>;
  by_segment_today: Record<"A" | "B" | "C" | "D", number>;
  channel_breakdown: { whatsapp: number; instagram: number; facebook: number; telegram: number; upload: number; manual: number; indiamart?: number; justdial?: number; meta_form?: number; website?: number; api?: number; store?: number };
  channel_breakdown_today: { whatsapp: number; instagram: number; facebook: number; telegram: number; upload: number; manual: number; indiamart?: number; justdial?: number; meta_form?: number; website?: number; api?: number; store?: number };
  total_leads: number;
  ad_attributed_leads: number;
  ad_attributed_leads_today: number;
  new_hot_leads_7d: number;
  new_hot_leads_daily: { day: string; count: number }[];
  new_hot_leads_7d_trend_pct: number | null;
}

export interface FollowUpQueueItem {
  id: string;
  lead_id: string;
  cadence: "1d" | "1w" | "1m";
  status: string;
  scheduled_for: string;
  sent_at: string | null;
  message_preview: string | null;
  skip_reason: string | null;
  last_error: string | null;
  lead_name: string | null;
  phone: string | null;
  segment: "A" | "B" | "C" | "D" | null;
}

export interface FollowUpSummary {
  pending: number;
  due_now: number;
  sent_7d: number;
  failed_7d: number;
  skipped_7d: number;
  by_cadence: { cadence: "1d" | "1w" | "1m"; pending: number; due_now: number; sent_7d: number }[];
  queue: FollowUpQueueItem[];
}

export interface FollowUpRunResult {
  processed: number;
  sent: number;
  failed: number;
  skipped: number;
  summary: FollowUpSummary;
}

export interface CallbackBoardItem {
  id: string;
  lead_id: string;
  scheduled_for: string;
  message_preview: string | null;
  status: string;
  lead: {
    id: string;
    name: string | null;
    phone: string | null;
    segment: "A" | "B" | "C" | "D" | null;
    assigned_to: string | null;
    score: number | null;
  };
  assigned_caller: {
    id: string;
    name: string;
    status: "active" | "break" | "logged_out";
    is_on_call: boolean;
  } | null;
  scheduled_by: {
    id: string;
    name: string | null;
  } | null;
}

export interface AdCampaignInsight {
  id: string;
  platform: "instagram" | "facebook" | "google";
  campaign_name: string;
  external_campaign_id: string | null;
  spend_inr: number;
  total_leads: number;
  progressive_leads: number;
  conversion_count: number;
  engaged_count: number;
  hot_count: number;
  segment_mix: { A: number; B: number; C: number; D: number };
  progressive_rate: number;
  conversion_rate: number;
  engaged_rate: number;
  cost_per_lead: number | null;
  cost_per_conversion: number | null;
  budget_recommendation: "increase" | "hold" | "decrease";
  suggestions: string[];
  adset_examples: string[];
  creative_examples: string[];
}

export interface AdPerformanceSummary {
  totals: {
    campaigns: number;
    tracked_leads: number;
    tracked_leads_today: number;
    progressive_rate_7d: number;
    conversion_rate_7d: number;
    recommend_increase: number;
    recommend_decrease: number;
  };
  campaigns: AdCampaignInsight[];
}

export interface TeamMember {
  user_id: string;
  role: "owner" | "caller";
  role_id?: string | null;
  role_name?: string | null;
  permissions?: string[];
  full_name?: string | null;
  force_password_reset?: boolean;
  created_at: string;
  caller_profile: {
    id: string;
    name: string | null;
    phone: string | null;
    overall_score: number | null;
    active: boolean;
    telecmi_agent_id: string | null;
  } | null;
}

export interface AttendanceDay {
  date: string;
  status: "present" | "absent" | "holiday" | "future";
}

export interface CallerAttendance {
  caller_id: string;
  days: AttendanceDay[];
  today_status: "present" | "absent" | "holiday" | "future";
}

export interface TeamAttendanceSummary {
  present_today: number;
  absent_today: number;
  attendance_rate_month: number;
}

export interface TeamAttendanceGridData {
  callers: { caller_id: string; name: string }[];
  days: string[];
  grid: Record<string, Record<string, "present" | "absent" | "holiday" | "future">>;
  summary: TeamAttendanceSummary;
}

export interface MyProfile {
  tenant_id: string;
  role: "owner" | "caller";
  role_id?: string | null;
  role_name?: string | null;
  role_slug?: string | null;
  permissions?: string[];
  force_password_reset?: boolean;
  caller_profile: {
    id: string;
    name: string | null;
    phone: string | null;
    overall_score: number | null;
  } | null;
}

export interface PermissionDef {
  key: string;
  label: string;
  group: string;
}

export interface ClientRole {
  id: string;
  tenant_id: string;
  name: string;
  slug: string | null;
  description: string | null;
  permissions: string[];
  is_system_template: boolean;
  is_telecaller: boolean;
  created_at: string;
  updated_at: string;
}

export interface RbacUser {
  user_id: string;
  full_name: string;
  email: string;
  role: "owner" | "caller";
  role_id: string | null;
  role_name: string;
  force_password_reset: boolean;
  created_at: string;
  caller_profile: TeamMember["caller_profile"];
}

export interface AuditLogEntry {
  id: string;
  actor_user_id: string | null;
  actor_role: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface TelecallingAnalytics {
  calls_today: number;
  calls_this_week: number;
  avg_duration_seconds: number | null;
  outcome_breakdown: Record<CallResult, number>;
  conversions_today?: number;
  followups_scheduled?: number;
  manual_status_breakdown?: Record<CallConnect, number>;
  per_caller: {
    caller_id: string;
    name: string;
    calls_today: number;
    /** Average score of the selected window's scored calls. Absent entirely
     *  for SIM clients -- they get no evaluation at all. */
    overall_score?: number | null;
    scored_calls?: number;
    connect_rate?: number;
    avg_talk_seconds?: number | null;
    talk_minutes_today?: number;
    idle_minutes_today?: number;
    avg_gap_seconds?: number | null;
    longest_idle_seconds?: number | null;
    bunking_flag?: boolean;
    speed_to_lead_min?: number | null;
  }[];
  connect_rate?: number;
  avg_talk_seconds?: number | null;
  talk_minutes_today?: number;
  idle_minutes_today?: number;
  avg_gap_seconds?: number | null;
  longest_idle_seconds?: number | null;
  speed_to_lead_min?: number | null;
  quality_avg?: number | null;
}

/** One row of Settings > Auto-Reply (backend automation_guards.SOURCES). ai/template: has that switch. */
export interface AutoReplySource {
  key: string;
  label: string;
  group: "channel" | "lead";
  hint: string;
  ai: boolean;
  template: boolean;
}

export interface TelecallingConfig {
  enabled?: boolean;
  calling_provider?: "telecmi" | "sim_basic";
  segments?: string[];
  channels?: string[];
  scripts?: Record<string, string>;
  assignment_mode?: "push" | "pull";
}

export interface FunnelAnalytics {
  total_leads: number;
  by_segment: { A: number; B: number; C: number; D: number };
  by_source: { whatsapp: number; instagram: number; upload: number };
  leads_this_week: number;
  avg_score: number | null;
}

export interface AnalyticsOverviewExtended {
  /** Optional: older cached responses and the operator console's narrower
   *  fetches may not carry these, so callers must tolerate absence. */
  money?: CompareMoney;
  response_times?: CompareResponseTimes;
  daily_leads: { day: string; count: number }[];
  daily_messages: { day: string; inbound: number; outbound: number; ai: number; human: number }[];
  funnel: { inquiries: number; engaged: number; hot: number; converted: number };
  ai_vs_human: { ai: number; human: number };
  unreplied_24h: number;
  converted_7d: number;
  converted_today: number;
  ai_handled_today: number;
  by_segment: Record<"A" | "B" | "C" | "D", number>;
  channel_breakdown: { whatsapp: number; instagram: number; facebook: number; telegram: number; upload: number; manual: number; indiamart?: number; justdial?: number; meta_form?: number; website?: number; api?: number; store?: number };
  total_leads: number;
}

export interface MessagingAnalytics {
  sent_today: number;
  received_today: number;
  ai_reply_rate: number | null;
  reply_source_breakdown: { ai: number; knowledge: number; reengagement: number; manual: number; unknown: number };
  daily_messages: { day: string; inbound: number; outbound: number }[];
}

export interface TelecallingComparisonMetrics {
  calls: number;
  connect_rate: number;
  conversions: number;
  avg_talk_seconds: number;
  idle_minutes: number;
}

export interface TelecallingAnalyticsExtended {
  calls_today: number;
  calls_this_week: number;
  avg_duration_seconds: number | null;
  total_minutes_today: number;
  calls_attempted?: number;
  connected_calls?: number;
  followups_scheduled?: number;
  outcome_breakdown: Record<CallResult, number>;
  manual_status_breakdown: Record<CallConnect, number>;
  conversions_today?: number;
  per_caller: {
    caller_id: string;
    name: string;
    calls_today: number;
    /** Average score of the selected window's scored calls. Absent entirely
     *  for SIM clients -- they get no evaluation at all. */
    overall_score?: number | null;
    scored_calls?: number;
    total_minutes_today: number;
    conversion_rate: number | null;
    connect_rate?: number;
    avg_talk_seconds?: number | null;
    talk_minutes_today?: number;
    idle_minutes_today?: number;
    avg_gap_seconds?: number | null;
    longest_idle_seconds?: number | null;
    bunking_flag?: boolean;
    speed_to_lead_min?: number | null;
  }[];
  calls_per_hour: { hour: number; label: string; count: number }[];
  calls_per_slot: { slot: string; count: number; caller_counts: Record<string, number> }[];
  connect_rate?: number;
  avg_talk_seconds?: number | null;
  talk_minutes_today?: number;
  idle_minutes_today?: number;
  avg_gap_seconds?: number | null;
  longest_idle_seconds?: number | null;
  speed_to_lead_min?: number | null;
  quality_avg?: number | null;
  comparison?: {
    yesterday: TelecallingComparisonMetrics;
    avg_7d: TelecallingComparisonMetrics;
  };
}

export interface FunnelAnalyticsExtended {
  total_leads: number;
  by_segment: { A: number; B: number; C: number; D: number };
  by_source: { whatsapp: number; instagram: number; facebook: number; telegram: number; upload: number; manual: number; indiamart?: number; justdial?: number; meta_form?: number; website?: number; api?: number; store?: number };
  leads_this_week: number;
  avg_score: number | null;
  score_histogram: { range: string; count: number }[];
  hot_lead_aging: { bucket: string; count: number }[];
}


/** One point on the comparison overlay. Two periods of different lengths are
 *  aligned by position ("Day N"), not calendar date, so they can be compared. */
export interface ComparePoint {
  index: number;
  label: string;
  current_day: string | null;
  current: number | null;
  previous_day: string | null;
  previous: number | null;
}

export interface CompareMetric {
  current: number;
  previous: number;
  /** null when the previous period had no activity — that is new activity,
   *  not a percentage increase. */
  delta_pct: number | null;
}

/** Ad spend joined to attributed leads. Empty object when a tenant has no
 *  ad data — callers must tolerate missing keys. */
export interface CompareMoney {
  spend?: number;
  impressions?: number;
  clicks?: number;
  ad_leads?: number;
  ad_hot_leads?: number;
  cost_per_lead?: number | null;
  cost_per_hot_lead?: number | null;
}

export interface CompareResponseTimes {
  inbound_total?: number;
  answered?: number;
  p50_seconds?: number | null;
  p90_seconds?: number | null;
}

/** Segment transitions written by the scoring engine — "what the AI did". */
export interface CompareMovement {
  promoted: number;
  demoted: number;
  promoted_to_hot: number;
  flows: { from: string; to: string; total: number }[];
}

export interface ComparePeriod {
  start: string;
  end: string;
  summary: Record<string, number>;
  money: CompareMoney;
  response: CompareResponseTimes;
  movement: CompareMovement;
  /** Only populated on `current` -- per-day segment counts for the mix chart. */
  daily_segment_mix?: { day: string; hot: number; warm: number; cold: number; disqualified: number }[];
  /** Only populated on `current`. */
  heatmap?: { dow: number; hour: number; total: number }[];
}

export interface ComparePayload {
  preset: string;
  current: ComparePeriod;
  previous: ComparePeriod | null;
  summary_text: string | null;
  metrics: Record<string, CompareMetric>;
  money_metrics: Record<string, CompareMetric>;
  response_metrics: Record<string, CompareMetric>;
  movement_metrics: Record<string, CompareMetric>;
  series: Record<string, ComparePoint[]>;
}

export type ComparisonMode = "off" | "previous" | "custom";

interface CompareRangeParams {
  preset: string;
  start?: string;
  end?: string;
}

export type CompareParams = CompareRangeParams & (
  | {
    comparison: Exclude<ComparisonMode, "custom">;
    comparison_start?: never;
    comparison_end?: never;
  }
  | {
    comparison: "custom";
    comparison_start: string;
    comparison_end: string;
  }
);

// Transient statuses worth a retry: server waking / restarting / behind a proxy.
const RETRYABLE_STATUS = new Set([502, 503, 504]);
// Cold-start (Render spin-up) can take 30–50s; give GETs room, keep mutations tight.
const GET_TIMEOUT_MS = 45_000;
const MUTATION_TIMEOUT_MS = 15_000;
const RETRY_DELAYS_MS = [2_000, 6_000, 15_000];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Marks failures safe to retry (network/timeout/transient status) vs. real errors.
class RetryableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RetryableError";
  }
}

async function apiFetchOnce<T>(path: string, opts: RequestInit, timeoutMs: number): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      ...opts,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
        ...(opts.headers as Record<string, string> ?? {}),
      },
    });
    if (!res.ok) {
      if (res.status === 401 && typeof window !== "undefined") {
        window.location.href = "/login";
      }
      // The overview is a read-only dashboard aggregate. A transient database
      // failure can surface as 500 while the service is recovering, so retry it
      // the same way as gateway failures before showing an error state.
      if (RETRYABLE_STATUS.has(res.status) || (res.status === 500 && path === "/api/v1/analytics/overview")) {
        throw new RetryableError(`Server unavailable (${res.status})`);
      }
      const err = await res.json().catch(() => ({ detail: "Request failed" }));
      const error = new Error(errorDetailText(err.detail, "Request failed")) as Error & { status?: number; detail?: unknown };
      error.status = res.status;
      // Raw body detail, so forms can place a 422's per-field messages (loc) next to the field.
      error.detail = err.detail;
      throw error;
    }
    return res.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new RetryableError("Request timed out — server took too long to respond");
    }
    // Safari says "Load failed", Chrome says "Failed to fetch", Firefox says "NetworkError…"
    // Any TypeError from fetch() is a network-layer failure — always retryable.
    if (err instanceof TypeError) {
      throw new RetryableError("Cannot reach server — it may be restarting.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Text for an error body's `detail`. FastAPI sends a string for most errors, but a list of
 * { msg, loc, ... } items for a 422 validation failure; those are joined with "; ".
 */
export function errorDetailText(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail || fallback;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (typeof d === "string" ? d : d && typeof d === "object" && typeof (d as { msg?: unknown }).msg === "string" ? (d as { msg: string }).msg : ""))
      .filter(Boolean);
    return msgs.length ? msgs.join("; ") : fallback;
  }
  return fallback;
}

/** GET a CSV and save it as `fileName`. */
async function downloadCsv(path: string, fileName: string): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, { headers });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(typeof err?.detail === "string" ? err.detail : `Download failed: ${res.status}`);
  }
  const url = window.URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const method = (opts.method ?? "GET").toUpperCase();
  // Only idempotent reads are retried — retrying a POST/PATCH/DELETE could
  // double-send a broadcast/message/assignment if the first reached the server.
  const idempotent = method === "GET" || method === "HEAD";
  const timeoutMs = idempotent ? GET_TIMEOUT_MS : MUTATION_TIMEOUT_MS;
  const maxAttempts = idempotent ? RETRY_DELAYS_MS.length + 1 : 1;

  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await apiFetchOnce<T>(path, opts, timeoutMs);
    } catch (err) {
      lastErr = err;
      if (!(err instanceof RetryableError) || attempt === maxAttempts - 1) break;
      await delay(RETRY_DELAYS_MS[attempt]);
    }
  }
  if (lastErr instanceof RetryableError) {
    throw new Error(
      lastErr.message.includes("timed out")
        ? lastErr.message
        : "Cannot reach server — it may be restarting. Try again in 30 seconds.",
    );
  }
  throw lastErr;
}

export interface AppNotification {
  id: string;
  type: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export interface PoolItem {
  kind: "handover";
  id: string;
  lead_id: string;
  lead_name: string | null;
  reason: string | null;
  created_at: string;
}

export type NotificationConfig = {
  push_enabled: boolean;
  events: Record<string, boolean>;
  claimable_threshold_minutes: number;
  claimable_audience: "telecallers_and_admin" | "telecallers_only" | "admin_only" | "specific";
  claimable_caller_ids: string[];
  quiet_hours: { enabled: boolean; start_hour: number; end_hour: number };
  whatsapp_notifications: {
    enabled: boolean;
    recipient_phones: string[];
    template_id: string | null;
    target_segments: string[];
    delay_minutes?: number;
  };
  /** Fired when a chat handover is created, not when a segment changes. */
  whatsapp_escalation_notifications: {
    enabled: boolean;
    recipient_phones: string[];
    template_id: string | null;
    target_segments: string[];
    delay_minutes?: number;
  };
};

export interface TimelineEvent {
  type: "status" | "call";
  id: string;
  status?: string;
  outcome?: string;
  manual_status?: string | null;
  started_at: string;
  ended_at?: string | null;
  duration_seconds: number | null;
  lead_name?: string;
  lead_phone?: string;
}

export interface AssignmentLogEntry {
  id: string;
  lead_id: string | null;
  lead_name: string | null;
  lead_phone: string | null;
  segment: string | null;
  event_type: "assigned" | "reassigned";
  caller_id: string | null;
  caller_name: string | null;
  prev_caller_name: string | null;
  reason: string | null;
  method: string | null;
  score: number | null;
  matched_segments: string[] | null;
  created_at: string;
}

export interface AssignmentLogSummary {
  assigned_today: number;
  by_caller: Record<string, { caller_name: string; count: number } | number>;
  by_segment: Record<string, number>;
}

export type IntakeStatus = "awaiting_payment" | "paid" | "resolved" | "cancelled";

// ---- Deals (docs/superpowers/specs/2026-09-25-deals-crm-design.md) ----
export type DealStage = "quoted" | "awaiting_payment" | "won" | "lost";
export type DealSource = "whatsapp" | "form" | "call" | "walk_in" | "manual" | "indiamart" | "justdial";
export type PaymentMethod = "razorpay" | "cash" | "upi" | "card" | "bank_transfer" | "other";
export type DealAttention = "unpaid_3d" | "link_expiring" | "refund";
export type DealSort = "created_at" | "total_paise" | "deal_number";

export interface DealFilters {
  stage?: DealStage;
  source?: DealSource[];
  q?: string;
  created_from?: string;
  created_to?: string;
  min_rupees?: number;
  max_rupees?: number;
  payment_method?: PaymentMethod[];
  product?: string[];
  attention?: DealAttention[];
}

export interface DealStageTotal {
  count: number;
  total_paise: number;
}

export interface DealSummaryStats {
  stages: Record<DealStage, DealStageTotal>;
  unpaid_3d: DealStageTotal;
  products: string[];
}

export interface DealListPage {
  data: DealSummary[];
  total: number;
  page: number;
  limit: number;
}

export interface DealItem {
  id: string;
  catalog_item_id: string | null;
  name: string;
  qty: number;
  unit_price_paise: number;
  gst_rate: number | null;
  line_total_paise: number;
}

export interface DealSummary {
  id: string;
  deal_number: number;
  deal_label: string;
  stage: DealStage;
  source: DealSource;
  total_paise: number;
  payment_method: PaymentMethod | null;
  payment_link: string | null;
  created_at: string;
  won_at: string | null;
  lost_at: string | null;
  lost_reason: string | null;
  lead: { id: string; name: string | null; phone: string | null };
  item_summary: string;
  item_count: number;
  // Optional: the board API may not send these yet; a missing field just hides its tag.
  last_activity_at?: string | null;
  link_expires_at?: string | null;
  refund_needed?: boolean | null;
}

export interface Deal extends DealSummary {
  items: DealItem[];
  notes: string | null;
  link_expires_at: string | null;
  razorpay_payment_id: string | null;
  intake_session_id: string | null;
  intake_answers: Record<string, unknown> | null;
}

export interface NewDealLine {
  catalog_item_id?: string;
  name: string;
  qty: number;
  unit_price_paise?: number;
}

export interface NewDealPayload {
  lead_id?: string;
  phone?: string;
  name?: string;
  items: NewDealLine[];
  source: "call" | "walk_in" | "manual";
  stage: "won" | "awaiting_payment" | "quoted";
  payment_method?: PaymentMethod;
  notes?: string;
}

export interface StockWarning {
  catalog_item_id: string;
  name: string;
  available: number | null;
}

export interface DealMutationResult {
  deal: Deal;
  payment_link?: string | null;
  message_sent?: boolean;
  stock_warnings: StockWarning[];
}

export interface DealStats {
  month: string;
  won_count: number;
  won_total_paise: number;
  lost_count: number;
  open_count: number;
  open_total_paise: number;
  by_source: Partial<Record<DealSource, { count: number; total_paise: number }>>;
  /** Only days with a sale; the Insights tab fills in the empty days itself. */
  by_day: {
    date: string;
    total_paise: number;
    count: number;
    by_source: Partial<Record<DealSource, { count: number; total_paise: number }>>;
  }[];
  top_items: { name: string; qty: number; total_paise: number }[];
  low_stock: { id: string; name: string; stock_quantity: number; held_quantity: number }[];
}

export interface BusinessProfile {
  legal_name: string;
  address: string;
  city: string;
  state: string;
  pincode: string;
  gstin: string;
  email: string;
  phone: string;
  prices_include_gst: boolean;
}

export interface StockMovement {
  id: string;
  catalog_item_id: string;
  delta: number;
  quantity_after: number;
  reason: "sale" | "restock" | "adjustment" | "return";
  deal_id: string | null;
  note: string | null;
  created_at: string;
}

export interface IntakeField {
  key: string;
  label: string;
  type: "text" | "date" | "choice";
}

export interface IntakeSession {
  id: string;
  lead_id: string;
  status: IntakeStatus;
  collected_data: Record<string, string>;
  field_schema: IntakeField[] | null;
  amount_paise: number | null;
  amount_mismatch: boolean;
  package_key: string | null;
  package_name: string | null;
  package_amount_paise: number | null;
  gst_percent?: number | null;
  gst_amount_paise?: number | null;
  payment_link: string | null;
  paid_at: string | null;
  created_at: string;
  leads: { name: string | null; phone: string | null } | null;
  /** The deal this form session became ("D-0014"), or null while it's still a form only. */
  deal_label?: string | null;
  /** Present only for a client connected to AstroTamil: did the paid question reach it? */
  astro?: { sent: boolean; question_id: number | null; horoscope_id: string | null };
}

export interface IntakeStats {
  totals: {
    messages: number;
    answered: number;
    pending: number;
    awaiting_payment: number;
    revenue_inr: number;
  };
  daily: { date: string; count: number }[];
}

export interface IntakePage {
  data: IntakeSession[];
  next_cursor: string | null;
  /** True only for a client with the AstroTamil connection; it unlocks the Resolved view. */
  astro_connected?: boolean;
}

export interface VerticalStarter {
  key: string;
  label: string;
  business_description: string;
}

export interface InterviewQuestion {
  id: string;
  question: string;
}

// Only the business description. How the assistant behaves comes from the
// platform-wide master prompt, which onboarding never writes.
export interface InterviewDraft {
  business_description: string;
}

export interface AskAnalyticsResult {
  answer: string;
  data: Record<string, unknown> | null;
  source: string | null;
}

/** Query params for every deals filter except stage, which only the list takes. */
function dealFilterParams(filters: Omit<DealFilters, "stage">): URLSearchParams {
  const search = new URLSearchParams();
  const lists = { source: filters.source, payment_method: filters.payment_method, product: filters.product, attention: filters.attention };
  for (const [key, values] of Object.entries(lists)) {
    if (values && values.length > 0) search.set(key, values.join(","));
  }
  if (filters.q) search.set("q", filters.q);
  if (filters.created_from) search.set("created_from", filters.created_from);
  if (filters.created_to) search.set("created_to", filters.created_to);
  if (filters.min_rupees != null) search.set("min_rupees", String(filters.min_rupees));
  if (filters.max_rupees != null) search.set("max_rupees", String(filters.max_rupees));
  return search;
}

// ---- SMS (Bulk9 client) — contract: docs/plans/2026-10-30-sms-api-contract.md ----
export interface SmsStatus {
  enabled: boolean;
  connected: boolean;
  support_contact: string | null;
  templates_ready: boolean;
}
export type SmsDltStatus = "approved" | "submitted";
export interface SmsDltEntity { entity_id: string; entity_name: string | null; status: SmsDltStatus; at: string | null }
export interface SmsDltSender extends SmsSender { status: SmsDltStatus; at: string | null }
/** DLT Manager. `error` is set (HTTP 200) when Bulk9 couldn't be read; submitted rows still show. */
export interface SmsDltList { entities: SmsDltEntity[]; senders: SmsDltSender[]; error: string | null }
export type SmsCreditStatus = "open" | "done" | "cancelled";
export interface SmsCreditRequest {
  id: string;
  amount: number;
  note: string | null;
  status: SmsCreditStatus;
  created_at: string;
  done_at: string | null;
}
export interface SmsBalance {
  sms_count: number;
  /** The client's own ₹ wallet at the rate their account manager set; null when Bulk9 didn't say. */
  wallet: number | null;
}
export type SmsWalletKind = "topup" | "outside_usage" | "campaign";
export interface SmsWalletItem {
  kind: SmsWalletKind;
  /** Signed: positive for a top-up, negative for usage. */
  sms: number;
  amount: number | null;
  label: string;
  campaign_id: string | null;
  at: string;
  balance_after: number | null;
}
export interface SmsWalletHistory { items: SmsWalletItem[]; checked_at: string | null }
export interface SmsSender { sender_id: string; entity_id: string; entity_name: string | null }
export type SmsTemplateType = "service" | "promotional";
export interface SmsTemplate {
  id: string;
  message_id: string | null;
  dlt_template_id: string | null;
  sender_id: string;
  entity_id: string | null;
  entity_name: string | null;
  message: string;
  var_count: number;
  /** DLT's category; "unclassified" = Bulk9 didn't say (shown as "Set by DLT", still sendable). */
  template_type: SmsTemplateType | "unclassified";
  status: "ready" | "submitted";
  last_synced_at: string | null;
}
/** One Indian day of the Delivery Reports chart. waiting = handed to the operator, no receipt yet. */
export interface SmsReportDay { day: string; delivered: number; failed: number; waiting: number; otp: number }
export interface SmsReportSummary {
  anril: Record<string, number>;
  /** Handed to the operator at night and still held by the TRAI 9 PM–10 AM rule. */
  held?: number;
  daily?: SmsReportDay[];
  bulk9: Record<string, unknown> | null;
  error: string | null;
}
export interface SmsTemplateList { templates: SmsTemplate[]; last_synced_at: string | null; error: string | null }
/** "typed" = a value typed next to each number (the Type numbers table), so `value` stays "". */
export type SmsVarSource = { source: "field"; value: string } | { source: "text"; value: string } | { source: "typed"; value: "" };
export interface SmsPreviewExcluded { lead_id?: string | null; name: string | null; phone: string | null; reason: string }
export interface SmsPreviewSample { lead_id?: string | null; name: string | null; content: string; segments: number; unicode: boolean }
export interface SmsPreview {
  total_segments: number;
  eligible_count: number;
  excluded: SmsPreviewExcluded[];
  /** Full count when `excluded` is capped at its first 1,000. */
  excluded_total?: number;
  samples: SmsPreviewSample[];
  estimated: boolean;
  rate_per_sms: number | null;
  estimated_amount: number | null;
}
export interface SmsOtpHistoryItem {
  id: string;
  mobile: string;
  action: "send" | "resend" | "verify";
  ok: boolean;
  message: string | null;
  created_at: string;
  /** "delivered" | "failed" once the operator reported; null = no report yet (or a verify row). */
  delivery_status: "delivered" | "failed" | null;
  delivered_at: string | null;
}
export type SmsCampaignStatus = "preparing" | "scheduled" | "sending" | "completed" | "cancelled";
export type SmsMessageStatus =
  | "queued" | "sending" | "submitted" | "delivered" | "failed" | "unknown" | "skipped" | "cancelled";
export interface SmsCampaign {
  id: string;
  name: string;
  template_text: string;
  sender_id: string;
  /** "unknown": DLT's category wasn't reported (Type my own, or a template Bulk9 didn't label). */
  template_type: SmsTemplateType | "unknown";
  status: SmsCampaignStatus;
  kind?: "template" | "manual";
  source?: SmsRecipientSource;
  /** Why a contacts campaign could not be built; shown to the client as-is. */
  build_error?: string | null;
  send_at: string | null;
  created_at: string;
  completed_at: string | null;
  counts: Record<SmsMessageStatus, number>;
  total: number;
  sms_used: number;
  amount_debited: number | null;
}
export interface SmsMessage {
  id: string;
  campaign_id: string | null;
  lead_id: string | null;
  lead_name: string | null;
  phone: string;
  content: string;
  status: SmsMessageStatus;
  failure_reason: string | null;
  sms_count: number | null;
  submitted_at: string | null;
  delivered_at: string | null;
  updated_at: string | null;
}
export interface SmsMessageFilters {
  campaign_id?: string;
  status?: string;
  from?: string;
  to?: string;
  search?: string;
  limit?: number;
  offset?: number;
}
export interface SmsOk { ok: boolean; message?: string }

export type SmsRecipientSource = "leads" | "contacts" | "numbers";
export interface SmsContact {
  id: string;
  phone: string;
  name: string | null;
  fields: Record<string, string>;
  group_ids: string[];
  promo_consent: boolean;
  created_at: string;
}
export interface SmsContactGroup { id: string; name: string; contacts: number; created_at: string }
export interface SmsUploadPreview {
  columns: string[];
  phone_column: string | null;
  name_column: string | null;
  sample: string[][];
  row_count: number;
}
export interface SmsSkippedRow { row: number; value: string; reason: string }
export interface SmsUploadResult {
  inserted: number;
  updated: number;
  skipped_count: number;
  skipped: SmsSkippedRow[];
  group_id: string | null;
}
/** Who a campaign goes to: exactly one of the three id/number lists matches `source`. */
export interface SmsRecipients {
  source: SmsRecipientSource;
  lead_ids?: string[];
  group_ids?: string[];
  numbers?: string[];
  /** Aligned with `numbers`: each row's values, indexed by variable position. */
  typed_values?: string[][];
  consent_confirmed?: boolean;
}
/** "Type my own" (Bulk9 route=dlt_manual): the exact approved text with every variable filled in. */
export interface SmsManualSpec { sender_id: string; entity_id: string; dlt_template_id: string; message: string }
export type SmsCampaignPreviewRequest = SmsRecipients & (
  | { kind?: "template"; template_id: string; variable_map?: SmsVarSource[] }
  | { kind: "manual"; manual: SmsManualSpec; variable_map?: [] }
);
export type SmsCampaignCreateRequest = SmsCampaignPreviewRequest & {
  name: string;
  send_at: string | null;
  idempotency_key: string;
};

async function smsMultipart<T>(path: string, fd: FormData): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, { method: "POST", body: fd, headers });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") window.location.href = "/login";
    const err = await res.json().catch(() => null);
    const error = new Error(errorDetailText(err?.detail, "Upload failed")) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

function smsMessageQuery(f: SmsMessageFilters): string {
  const qs = new URLSearchParams();
  if (f.campaign_id) qs.set("campaign_id", f.campaign_id);
  if (f.status) qs.set("status", f.status);
  if (f.from) qs.set("from", f.from);
  if (f.to) qs.set("to", f.to);
  if (f.search) qs.set("search", f.search);
  if (f.limit != null) qs.set("limit", String(f.limit));
  if (f.offset != null) qs.set("offset", String(f.offset));
  return qs.toString();
}

// ---- Anril OTP (/api/v1/otp-console) ----
export type OtpMode = "sms" | "whatsapp" | "both" | "sms_then_whatsapp";
export type OtpSettings = {
  default_mode: OtpMode;
  fallback_wait_seconds: number;
  max_per_hour: number;
  expiry_minutes: number;
  code_length: number;
  max_attempts: number;
  sms_sender_id: string | null;
  sms_message_id: string | null;
  wa_template_name: string | null;
  wa_template_language: string | null;
  status_webhook_url: string | null;
  has_webhook_secret: boolean;
};
export type OtpChannel = { ready: boolean; problem: string | null };
export type OtpOverview = {
  settings: OtpSettings;
  channels: { sms: OtpChannel; whatsapp: OtpChannel };
  not_requested_7d: number;
  failed_updates_7d: number;
  limits: Record<"fallback_wait_seconds" | "max_per_hour" | "expiry_minutes" | "code_length" | "max_attempts", [number, number]>;
};
export type OtpView = {
  otp_id: string;
  phone: string;
  mode: OtpMode;
  source: "anril" | "client";
  status: "pending" | "verified" | "expired" | "locked" | "not_requested" | "failed";
  ref: string | null;
  expires_at: string;
  verified_at: string | null;
  sms: { status: "none" | "sent" | "delivered" | "failed"; error: string | null };
  whatsapp: { status: "none" | "sent" | "delivered" | "read" | "failed"; error: string | null };
  whatsapp_backup_sent: boolean;
  not_requested: boolean;
  created_at: string;
};
export type OtpHistoryItem = OtpView & { origin: "dashboard" | "api" | "bot" | "telecaller"; code: string; attempts: number };
export type OtpVerifyResult = { verified: boolean; reason: string | null; message: string | null; attempts_left: number; otp_id: string };
export type OtpKey = { id: string; key_prefix: string; status: "active" | "revoked"; created_at: string; revoked_at: string | null; last_used_at: string | null };

export const api = {
  otp: {
    overview: () => apiFetch<OtpOverview>("/api/v1/otp-console/overview"),
    saveSettings: (patch: Partial<Omit<OtpSettings, "has_webhook_secret">>) =>
      apiFetch<{ settings: OtpSettings }>("/api/v1/otp-console/settings", { method: "PUT", body: JSON.stringify(patch) }),
    rotateWebhookSecret: () => apiFetch<{ secret: string }>("/api/v1/otp-console/webhook-secret", { method: "POST" }),
    testWebhook: () => apiFetch<{ ok: boolean; error: string | null }>("/api/v1/otp-console/webhook-test", { method: "POST" }),
    send: (data: { phone: string; mode?: OtpMode; code?: string }) =>
      apiFetch<OtpView>("/api/v1/otp-console/send", { method: "POST", body: JSON.stringify(data) }),
    verify: (data: { otp_id: string; code: string }) =>
      apiFetch<OtpVerifyResult>("/api/v1/otp-console/verify", { method: "POST", body: JSON.stringify(data) }),
    history: (params: { before?: string; limit?: number } = {}) => {
      const qs = new URLSearchParams();
      if (params.before) qs.set("before", params.before);
      if (params.limit != null) qs.set("limit", String(params.limit));
      const q = qs.toString();
      return apiFetch<{ items: OtpHistoryItem[] }>(`/api/v1/otp-console/history${q ? `?${q}` : ""}`);
    },
    historyItem: (id: string) =>
      apiFetch<{
        item: OtpHistoryItem;
        updates: { event: string; status: string; attempts: number; last_error: string | null; created_at: string; delivered_at: string | null }[];
      }>(`/api/v1/otp-console/history/${encodeURIComponent(id)}`),
    smsTemplates: () =>
      apiFetch<{ templates: { sender_id: string; message_id: string; message: string }[]; problem: string | null }>(
        "/api/v1/otp-console/sms-templates",
      ),
    whatsappTemplates: () =>
      apiFetch<{ templates: { name: string; language: string; status: string; body: string | null }[]; problem: string | null }>(
        "/api/v1/otp-console/whatsapp-templates",
      ),
    createWhatsappTemplate: (data: { name: string; language: string }) =>
      apiFetch<{ name: string; language: string; status: string }>("/api/v1/otp-console/whatsapp-templates", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    keys: () => apiFetch<{ keys: OtpKey[] }>("/api/v1/otp-console/keys"),
    createKey: () =>
      apiFetch<{ id: string; key: string; key_prefix: string; created_at: string }>("/api/v1/otp-console/keys", { method: "POST" }),
    revokeKey: (id: string) =>
      apiFetch<{ ok: boolean }>(`/api/v1/otp-console/keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
  },
  sms: {
    status: () => apiFetch<SmsStatus>("/api/v1/sms/status"),
    balance: () => apiFetch<SmsBalance>("/api/v1/sms/balance"),
    walletHistory: (limit = 100) => apiFetch<SmsWalletHistory>(`/api/v1/sms/wallet/history?limit=${limit}`),
    senders: () => apiFetch<{ senders: SmsSender[] }>("/api/v1/sms/senders"),
    templates: () => apiFetch<SmsTemplateList>("/api/v1/sms/templates"),
    refreshTemplates: () => apiFetch<SmsTemplateList>("/api/v1/sms/templates/refresh", { method: "POST" }),
    addEntity: (data: { entity_name: string; entity_id: string }) =>
      apiFetch<SmsOk>("/api/v1/sms/dlt/entity", { method: "POST", body: JSON.stringify(data) }),
    addSender: (data: { entity_id: string; sender_id: string }) =>
      apiFetch<SmsOk>("/api/v1/sms/dlt/sender", { method: "POST", body: JSON.stringify(data) }),
    addSenderExcel: (data: { entity_id: string; file: File }) => {
      const fd = new FormData();
      fd.append("entity_id", data.entity_id);
      fd.append("file", data.file);
      return smsMultipart<SmsOk>("/api/v1/sms/dlt/sender-excel", fd);
    },
    addTemplate: (data: {
      entity_id: string;
      sender_ids: string[];
      dlt_template_id: string;
      message_text: string;
      template_type: SmsTemplateType;
    }) => apiFetch<SmsOk>("/api/v1/sms/dlt/template", { method: "POST", body: JSON.stringify(data) }),
    addTemplateExcel: (data: { entity_id: string; file: File }) => {
      const fd = new FormData();
      fd.append("entity_id", data.entity_id);
      fd.append("file", data.file);
      return smsMultipart<SmsOk>("/api/v1/sms/dlt/template-excel", fd);
    },
    campaignFields: (source: SmsRecipientSource = "leads", groupIds: string[] = []) => {
      const qs = new URLSearchParams();
      if (source !== "leads") qs.set("source", source);
      if (source === "contacts" && groupIds.length > 0) qs.set("group_ids", groupIds.join(","));
      const q = qs.toString();
      return apiFetch<{ fields: { key: string; label: string }[] }>(`/api/v1/sms/campaigns/fields${q ? `?${q}` : ""}`);
    },
    previewCampaign: (data: SmsCampaignPreviewRequest) =>
      apiFetch<SmsPreview>("/api/v1/sms/campaigns/preview", { method: "POST", body: JSON.stringify(data) }),
    createCampaign: (data: SmsCampaignCreateRequest) =>
      apiFetch<SmsCampaign>("/api/v1/sms/campaigns", { method: "POST", body: JSON.stringify(data) }),
    campaigns: (limit = 50, offset = 0) =>
      apiFetch<{ campaigns: SmsCampaign[] }>(`/api/v1/sms/campaigns?limit=${limit}&offset=${offset}`),
    campaign: (id: string) => apiFetch<SmsCampaign>(`/api/v1/sms/campaigns/${encodeURIComponent(id)}`),
    cancelCampaign: (id: string) =>
      apiFetch<SmsCampaign>(`/api/v1/sms/campaigns/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
    rescheduleCampaign: (id: string, send_at: string) =>
      apiFetch<SmsCampaign>(`/api/v1/sms/campaigns/${encodeURIComponent(id)}/reschedule`, {
        method: "POST",
        body: JSON.stringify({ send_at }),
      }),
    deleteCampaign: (id: string) =>
      apiFetch<SmsOk>(`/api/v1/sms/campaigns/${encodeURIComponent(id)}`, { method: "DELETE" }),
    messages: (filters: SmsMessageFilters = {}) =>
      apiFetch<{ messages: SmsMessage[]; total: number }>(`/api/v1/sms/messages?${smsMessageQuery(filters)}`),
    exportMessagesCsv: async (filters: SmsMessageFilters = {}) => {
      // The export covers every matching row, so paging fields are dropped.
      const rest: SmsMessageFilters = { ...filters, limit: undefined, offset: undefined };
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/sms/messages/export.csv?${smsMessageQuery(rest)}`, { headers });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(typeof err?.detail === "string" ? err.detail : `Export failed: ${res.status}`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "sms_messages.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
    reportSummary: (from: string, to: string) =>
      apiFetch<SmsReportSummary>(
        `/api/v1/sms/reports/summary?from=${from}&to=${to}`,
      ),
    reportLogs: (from: string, to: string, page = 1, limit = 25) =>
      apiFetch<{ logs: Record<string, unknown>[]; page: number; error: string | null }>(
        `/api/v1/sms/reports/logs?from=${from}&to=${to}&page=${page}&limit=${limit}`,
      ),
    developerKey: () => apiFetch<{ api_key: string }>("/api/v1/sms/developer/key"),
    otpSend: (data: { mobile: string; otp_id: string; otp_length?: number; otp_expiry?: number; variables_values?: string }) =>
      apiFetch<{ ok: boolean; request_id?: string; message?: string }>("/api/v1/sms/otp/send", {
        method: "POST",
        body: JSON.stringify({ otp_length: 6, otp_expiry: 15, ...data }),
      }),
    contacts: (params: { search?: string; group_id?: string; limit?: number; offset?: number } = {}) => {
      const qs = new URLSearchParams();
      if (params.search) qs.set("search", params.search);
      if (params.group_id) qs.set("group_id", params.group_id);
      qs.set("limit", String(params.limit ?? 50));
      qs.set("offset", String(params.offset ?? 0));
      return apiFetch<{ items: SmsContact[]; total: number }>(`/api/v1/sms/contacts?${qs}`);
    },
    addContact: (data: { phone: string; name?: string; group_id?: string; consent: boolean }) =>
      apiFetch<SmsContact>("/api/v1/sms/contacts", { method: "POST", body: JSON.stringify(data) }),
    pasteContacts: (data: { text: string; group_id?: string; consent: boolean }) =>
      apiFetch<SmsUploadResult>("/api/v1/sms/contacts/paste", { method: "POST", body: JSON.stringify(data) }),
    previewContactUpload: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return smsMultipart<SmsUploadPreview>("/api/v1/sms/contacts/upload/preview", fd);
    },
    uploadContacts: (data: {
      file: File;
      group_id?: string;
      group_name?: string;
      phone_column?: string;
      name_column?: string;
      consent: boolean;
    }) => {
      const fd = new FormData();
      fd.append("file", data.file);
      if (data.group_id) fd.append("group_id", data.group_id);
      else if (data.group_name) fd.append("group_name", data.group_name);
      if (data.phone_column) fd.append("phone_column", data.phone_column);
      if (data.name_column) fd.append("name_column", data.name_column);
      fd.append("consent", data.consent ? "true" : "false");
      return smsMultipart<SmsUploadResult>("/api/v1/sms/contacts/upload", fd);
    },
    deleteContacts: (ids: string[]) =>
      apiFetch<{ deleted: number }>("/api/v1/sms/contacts/delete", { method: "POST", body: JSON.stringify({ ids }) }),
    addContactsToGroup: (groupId: string, ids: string[]) =>
      apiFetch<{ changed: number }>(`/api/v1/sms/contacts/groups/${encodeURIComponent(groupId)}/add`, {
        method: "POST",
        body: JSON.stringify({ ids }),
      }),
    removeContactsFromGroup: (groupId: string, ids: string[]) =>
      apiFetch<{ changed: number }>(`/api/v1/sms/contacts/groups/${encodeURIComponent(groupId)}/remove`, {
        method: "POST",
        body: JSON.stringify({ ids }),
      }),
    contactGroups: () => apiFetch<{ groups: SmsContactGroup[] }>("/api/v1/sms/contact-groups"),
    createContactGroup: (name: string) =>
      apiFetch<SmsContactGroup>("/api/v1/sms/contact-groups", { method: "POST", body: JSON.stringify({ name }) }),
    renameContactGroup: (id: string, name: string) =>
      apiFetch<SmsContactGroup>(`/api/v1/sms/contact-groups/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      }),
    deleteContactGroup: (id: string, withContacts: boolean) =>
      apiFetch<{ deleted_contacts: number }>(
        `/api/v1/sms/contact-groups/${encodeURIComponent(id)}?with_contacts=${withContacts ? "true" : "false"}`,
        { method: "DELETE" },
      ),
    otpVerify: (data: { mobile: string; otp: string }) =>
      apiFetch<SmsOk>("/api/v1/sms/otp/verify", { method: "POST", body: JSON.stringify(data) }),
    otpResend: (data: { mobile: string }) =>
      apiFetch<SmsOk>("/api/v1/sms/otp/resend", { method: "POST", body: JSON.stringify(data) }),
    otpHistory: (limit = 50, offset = 0) =>
      apiFetch<{ items: SmsOtpHistoryItem[]; total: number }>(`/api/v1/sms/otp/history?limit=${limit}&offset=${offset}`),
    dltList: () => apiFetch<SmsDltList>("/api/v1/sms/dlt/entities"),
    creditRequests: () => apiFetch<{ items: SmsCreditRequest[] }>("/api/v1/sms/credit-requests"),
    requestCredit: (data: { amount: number; note?: string }) =>
      apiFetch<SmsCreditRequest>("/api/v1/sms/credit-requests", { method: "POST", body: JSON.stringify(data) }),
    exportGroupCsv: async (groupId: string, groupName: string) => {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/sms/contact-groups/${encodeURIComponent(groupId)}/export.csv`, { headers });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(typeof err?.detail === "string" ? err.detail : `Export failed: ${res.status}`);
      }
      const url = window.URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `${groupName.replace(/[^A-Za-z0-9 _-]/g, "").trim() || "group"}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
  },
  scheduledOverview: {
    get: () => apiFetch<ScheduledOverview>("/api/v1/scheduled-overview"),
    bulk: (body: ScheduledBulkRequest) =>
      apiFetch<ScheduledBulkResult>("/api/v1/scheduled-overview/bulk", { method: "POST", body: JSON.stringify(body) }),
    broadcastFile: (id: string) =>
      apiFetch<{ url: string; file_name: string }>(`/api/v1/scheduled-overview/broadcasts/${id}/file`),
  },
  ask: (question: string) =>
    apiFetch<AskAnalyticsResult>("/api/v1/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  leads: {
    list: async (params?: {
      segment?: string;
      limit?: number;
      skip?: number;
      assigned_to?: string;
      source_filter?: string;
      broadcast_id?: string;
      ad_campaign_id?: string;
      date_from?: string;
      date_to?: string;
      search?: string;
    }) => {
      const qs = new URLSearchParams();
      if (params?.segment) qs.set("segment", params.segment);
      if (params?.search) qs.set("search", params.search);
      if (params?.assigned_to) qs.set("assigned_to", params.assigned_to);
      if (params?.source_filter) qs.set("source_filter", params.source_filter);
      if (params?.broadcast_id) qs.set("broadcast_id", params.broadcast_id);
      if (params?.ad_campaign_id) qs.set("ad_campaign_id", params.ad_campaign_id);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      if (typeof params?.limit === "number" && Number.isFinite(params.limit)) {
        const normalizedLimit = Math.min(Math.max(Math.trunc(params.limit), 1), MAX_LEADS_LIST_LIMIT);
        qs.set("limit", String(normalizedLimit));
      }
      if (params?.skip) qs.set("skip", String(params.skip));
      const res = await apiFetch<{ data: Lead[] }>(`/api/v1/leads/?${qs}`);
      return res.data || [];
    },
    listPage: async (params: {
      segment?: string;
      page?: number;
      limit?: number;
      assigned_to?: string;
      source_filter?: string;
      broadcast_id?: string;
      ad_campaign_id?: string;
      date_from?: string;
      date_to?: string;
      search?: string;
      reply_window?: "open" | "closed";
      sort?: "newest" | "oldest" | "urgent";
    }) => {
      const qs = new URLSearchParams();
      if (params?.segment) qs.set("segment", params.segment);
      if (params?.search) qs.set("search", params.search);
      if (params?.assigned_to) qs.set("assigned_to", params.assigned_to);
      if (params?.source_filter) qs.set("source_filter", params.source_filter);
      if (params?.broadcast_id) qs.set("broadcast_id", params.broadcast_id);
      if (params?.ad_campaign_id) qs.set("ad_campaign_id", params.ad_campaign_id);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      if (params?.reply_window) qs.set("reply_window", params.reply_window);
      if (params?.sort) qs.set("sort", params.sort);
      if (typeof params?.page === "number" && Number.isFinite(params.page)) {
        qs.set("page", String(params.page));
      }
      if (typeof params?.limit === "number" && Number.isFinite(params.limit)) {
        const normalizedLimit = Math.min(Math.max(Math.trunc(params.limit), 1), MAX_LEADS_LIST_LIMIT);
        qs.set("limit", String(normalizedLimit));
      }
      const res = await apiFetch<{ data: Lead[]; total: number; page: number; limit: number }>(`/api/v1/leads/?${qs}`);
      return { data: res.data || [], total: res.total ?? 0 };
    },
    get: (id: string) => apiFetch<Lead>(`/api/v1/leads/${id}`),
    update: (id: string, data: Partial<Pick<Lead, "name" | "score" | "segment">>) =>
      apiFetch<Lead>(`/api/v1/leads/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    convert: (id: string, notes?: string) =>
      apiFetch<Lead>(`/api/v1/leads/${id}/convert`, {
        method: "POST",
        body: JSON.stringify({ notes: notes ?? null }),
      }),
    sendDetailsContext: (leadId: string) =>
      apiFetch<SendDetailsContext>(`/api/v1/leads/${leadId}/send-details`),
    sendDetails: (leadId: string, body: { text: string } | { template_id: string; variables: string[] }) =>
      apiFetch<Message>(`/api/v1/leads/${leadId}/send-details`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    scheduledTemplates: async (leadId: string) =>
      (await apiFetch<{ items: ScheduledTemplate[] }>(`/api/v1/leads/${leadId}/scheduled-templates`)).items ?? [],
    scheduleTemplate: (
      leadId: string,
      body: { template_id: string; variables: string[]; send_at: string; batch_id?: string; batch_label?: string },
    ) =>
      apiFetch<ScheduledTemplate>(`/api/v1/leads/${leadId}/scheduled-templates`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    rescheduleTemplate: (id: string, sendAt: string) =>
      apiFetch<ScheduledTemplate>(`/api/v1/leads/scheduled-templates/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ send_at: sendAt }),
      }),
    cancelScheduledTemplate: (id: string) =>
      apiFetch<ScheduledTemplate>(`/api/v1/leads/scheduled-templates/${id}/cancel`, { method: "POST" }),
    restoreScheduledTemplate: (id: string) =>
      apiFetch<ScheduledTemplate>(`/api/v1/leads/scheduled-templates/${id}/restore`, { method: "POST" }),
    composeSchedule: (body: { phone: string; name?: string; template_id: string; variables: string[]; send_at: string }) =>
      apiFetch<ScheduledTemplate & { phone: string }>(`/api/v1/leads/compose/schedule`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    toggleAI: (id: string, enabled: boolean) =>
      apiFetch<Lead>(`/api/v1/leads/${id}/ai`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),
    sendMessage: (id: string, content: string) =>
      apiFetch<Message>(`/api/v1/leads/${id}/send`, {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
    sendMedia: async (id: string, file: File, caption?: string): Promise<Message> => {
      const authHeaders = await getAuthHeaders();
      const fd = new FormData();
      fd.append("file", file);
      if (caption) fd.append("caption", caption);
      const res = await fetch(`${API_URL}/api/v1/leads/${id}/send-media`, {
        method: "POST",
        body: fd,
        headers: { ...authHeaders },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Media send failed" }));
        throw new Error(err.detail || "Media send failed");
      }
      return res.json();
    },
    shareProduct: (leadId: string, itemId: string) =>
      apiFetch<Message>(`/api/v1/leads/${leadId}/share-product`, {
        method: "POST",
        body: JSON.stringify({ item_id: itemId }),
      }),
    compose: (phone: string, content: string, name?: string) =>
      apiFetch<{ lead_id: string; sid: string; phone: string }>(`/api/v1/leads/compose`, {
        method: "POST",
        body: JSON.stringify({ phone, content, name }),
      }),
    composeTemplate: (phone: string, templateId: string, variables: string[], name?: string) =>
      apiFetch<{ lead_id: string; sid: string; phone: string }>(`/api/v1/leads/compose`, {
        method: "POST",
        body: JSON.stringify({ phone, template_id: templateId, variables, name }),
      }),
    composeTemplates: async () =>
      (await apiFetch<{ templates: SendDetailsTemplate[] }>(`/api/v1/leads/compose/templates`)).templates ?? [],
    broadcastPreview: (filters: BroadcastFilters) =>
      apiFetch<BroadcastPreview>(`/api/v1/leads/broadcast/preview`, {
        method: "POST",
        body: JSON.stringify(filters),
      }),
    broadcast: (data: BroadcastFilters & { message: string }) =>
      apiFetch<{ total: number; sent: number; failed: number; skipped_window: number }>(
        `/api/v1/leads/broadcast`,
        {
          method: "POST",
          body: JSON.stringify(data),
        }
      ),
    delete: (id: string) =>
      apiFetch<{ success: boolean; message: string }>(`/api/v1/leads/${id}`, {
        method: "DELETE",
      }),
    clearData: (id: string) =>
      apiFetch<{ success: boolean; message: string }>(`/api/v1/leads/${id}/clear-data`, {
        method: "DELETE",
      }),
    pin: (id: string) =>
      apiFetch<Lead>(`/api/v1/leads/${id}/pin`, {
        method: "PATCH",
      }),
    archive: (id: string) =>
      apiFetch<Lead>(`/api/v1/leads/${id}/archive`, {
        method: "PATCH",
      }),
    block: (id: string) =>
      apiFetch<Lead>(`/api/v1/leads/${id}/block`, {
        method: "PATCH",
      }),
    release: (id: string) =>
      apiFetch<{ released: boolean }>(`/api/v1/leads/${id}/release`, {
        method: "PATCH",
      }),
    messages: async (id: string) => {
      const res = await apiFetch<Message[] | { data: Message[] }>(`/api/v1/leads/${id}/messages`);
      return Array.isArray(res) ? res : res.data || [];
    },
    callLogs: async (leadId: string) => {
      const res = await apiFetch<{ data: CallLog[] }>(`/api/v1/leads/${leadId}/call-logs`);
      return res.data || [];
    },
    preCallBrief: async (leadId: string, force = false) =>
      apiFetch<{ brief: string; opener: string }>(
        `/api/v1/leads/${leadId}/pre-call-brief${force ? "?force=true" : ""}`,
        { method: "POST" },
      ),
    exportUrl: (segment?: string) =>
      `${API_URL}/api/v1/leads/export${segment ? `?segment=${segment}` : ""}`,
    exportLeads: async (segment?: string) => {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/leads/export${segment ? `?segment=${segment}` : ""}`, { headers });
      if (!res.ok) throw new Error(`Export failed: ${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `leads_${segment || "all"}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
    exportAssigned: async () => {
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/leads/export-assigned`, { headers });
      if (!res.ok) throw new Error(`Export failed: ${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `my_assigned_leads.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
    assign: (leadId: string, callerId: string | null) =>
      apiFetch<Lead>(`/api/v1/leads/${leadId}/assign`, {
        method: "PATCH",
        body: JSON.stringify({ caller_id: callerId }),
      }),
    bulkAssign: (leadIds: string[], callerId: string | null) =>
      apiFetch<{ success: boolean; updated: number }>(`/api/v1/leads/bulk-assign`, {
        method: "POST",
        body: JSON.stringify({ lead_ids: leadIds, caller_id: callerId }),
      }),
    takeover: (leadId: string) =>
      apiFetch<{ success: boolean; assigned_to: string }>(`/api/v1/leads/${leadId}/takeover`, {
        method: "POST",
      }),
  },
  assignmentLog: {
    list: async (params?: { page?: number; limit?: number; caller_id?: string; segment?: string; from_date?: string; to_date?: string }) => {
      const qs = new URLSearchParams();
      if (params?.page) qs.set("page", String(params.page));
      if (params?.limit) qs.set("limit", String(params.limit));
      if (params?.caller_id) qs.set("caller_id", params.caller_id);
      if (params?.segment) qs.set("segment", params.segment);
      if (params?.from_date) qs.set("from_date", params.from_date);
      if (params?.to_date) qs.set("to_date", params.to_date);
      return apiFetch<{ data: AssignmentLogEntry[]; meta: { total: number; page: number; limit: number } }>(`/api/v1/assignment-log?${qs.toString()}`);
    },
    summary: () =>
      apiFetch<AssignmentLogSummary>(`/api/v1/assignment-log/summary`),
    exportCsv: async (params?: { caller_id?: string; segment?: string; from_date?: string; to_date?: string }) => {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams({ format: "csv" });
      if (params?.caller_id) qs.set("caller_id", params.caller_id);
      if (params?.segment) qs.set("segment", params.segment);
      if (params?.from_date) qs.set("from_date", params.from_date);
      if (params?.to_date) qs.set("to_date", params.to_date);
      const res = await fetch(`${API_URL}/api/v1/assignment-log?${qs.toString()}`, { headers });
      if (!res.ok) throw new Error(`Export failed: ${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "assignment-log.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
  },
  callers: {
    create: (name: string, phone: string) =>
      apiFetch<Caller>(`/api/v1/callers/`, {
        method: "POST",
        body: JSON.stringify({ name, phone }),
      }),
    update: (id: string, data: { name?: string; phone?: string; telecmi_agent_id?: string | null; telecmi_agent_password?: string | null; shift_start_hour?: number | null; shift_end_hour?: number | null }) =>
      apiFetch<Caller>(`/api/v1/callers/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    remove: (id: string) =>
      apiFetch<{ deleted: boolean }>(`/api/v1/callers/${id}`, { method: "DELETE" }),
    generateSyncToken: (id: string) =>
      apiFetch<{ sync_token: string }>(`/api/v1/callers/${id}/sync-token`, { method: "POST" }),
    getSyncToken: (id: string) =>
      apiFetch<{ sync_token: string }>(`/api/v1/callers/${id}/sync-token`, { method: "GET" }),
    list: async () => {
      const res = await apiFetch<{ data: Caller[]; admin_caller?: Caller | null }>(`/api/v1/callers/`);
      return { data: res.data || [], admin_caller: res.admin_caller ?? null };
    },
    logs: async (id: string) => {
      const res = await apiFetch<{ data: CallLog[] }>(`/api/v1/callers/${id}/logs`);
      return res.data || [];
    },
    myStatus: () =>
      apiFetch<{ status: string; caller_id: string | null }>(`/api/v1/callers/my-status`),
    setMyStatus: (status: "active" | "break" | "logged_out") =>
      apiFetch<{ status: string; changed_at: string }>(`/api/v1/callers/my-status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    myStats: () =>
      apiFetch<CallerStats>(`/api/v1/callers/my-stats`),
    statusSummary: (id: string) =>
      apiFetch<{
        active_minutes_today: number;
        break_minutes_today: number;
        idle_minutes_today: number;
        current_status: string;
        since: string;
        first_login_at: string | null;
        last_logout_at: string | null;
        breaks: { started_at: string; ended_at: string | null; duration_minutes: number }[];
        scheduled_count: number;
      }>(`/api/v1/callers/${id}/status-summary`),
    getTimeline: (id: string, date?: string) => {
      const q = date ? `?date=${encodeURIComponent(date)}` : "";
      return apiFetch<{ data: TimelineEvent[] }>(`/api/v1/callers/${id}/timeline${q}`);
    },
    winners: () =>
      apiFetch<{ daily: Winner | null; monthly: Winner | null }>(`/api/v1/callers/winners`),
    myCallsToday: () =>
      apiFetch<{ data: CallLog[] }>(`/api/v1/callers/my-calls-today`).then(res => res.data || []),
    myPerformance: () =>
      apiFetch<{ target: number; achieved: number }>(`/api/v1/callers/my-performance`),
    updateTarget: (callerId: string, target: number) =>
      apiFetch<Caller>(`/api/v1/callers/${callerId}/target`, {
        method: "PATCH",
        body: JSON.stringify({ target }),
      }),
  },
  calls: {
    initiate: (target: { leadId?: string; phone?: string; callbackJobId?: string }, callerId?: string) =>
      apiFetch<{ call_log_id: string; call_sid: string; status: string; provider: "telecmi" | "sim_basic"; lead_id: string | null; lead_name: string | null; phone?: string | null }>(
        `/api/v1/calls/initiate`,
        { method: "POST", keepalive: true, body: JSON.stringify({ lead_id: target.leadId, phone: target.phone, caller_id: callerId, callback_job_id: target.callbackJobId }) }
      ),
    recent: async (limit = 20, callerId?: string) => {
      const qs = new URLSearchParams({ limit: String(limit) });
      if (callerId) qs.set("caller_id", callerId);
      const res = await apiFetch<{ data: CallLog[] }>(`/api/v1/calls/recent?${qs.toString()}`);
      return res.data || [];
    },
    saveWrapup: (callLogId: string, payload: WrapupPayload) =>
      apiFetch<WrapupSaved>(`/api/v1/calls/${callLogId}/outcome`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    wrapupContext: (target: { leadId?: string; callLogId?: string }) => {
      const q = new URLSearchParams();
      if (target.leadId) q.set("lead_id", target.leadId);
      if (target.callLogId) q.set("call_log_id", target.callLogId);
      return apiFetch<WrapupContext>(`/api/v1/calls/wrapup-context?${q.toString()}`);
    },
    statsToday: () =>
      apiFetch<{ calls_today: number; conversions_today: number }>(`/api/v1/calls/stats-today`),
    recentByLeads: (leadIds: string[]) =>
      apiFetch<Record<string, string>>(
        `/api/v1/calls/recent-by-leads?lead_ids=${leadIds.slice(0, 50).join(",")}`,
      ),
    deleteLog: (callLogId: string) =>
      apiFetch<{ deleted: boolean }>(`/api/v1/calls/${callLogId}`, { method: "DELETE" }),
    getLog: (callLogId: string) =>
      apiFetch<CallLog>(`/api/v1/calls/${callLogId}`),
    retryAi: (callLogId: string) =>
      apiFetch<{ ok: boolean }>(`/api/v1/calls/${callLogId}/retry-ai`, { method: "POST" }),
    alerts: (params: { type?: CallAlertType; caller_id?: string; seen?: boolean; page?: number; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (params.type) q.set("type", params.type);
      if (params.caller_id) q.set("caller_id", params.caller_id);
      q.set("seen", String(params.seen ?? false));
      q.set("page", String(params.page ?? 1));
      q.set("limit", String(params.limit ?? 20));
      return apiFetch<{ data: CallAlert[]; total: number; page: number; limit: number }>(`/api/v1/calls/alerts?${q}`);
    },
    alertCount: () => apiFetch<{ count: number }>("/api/v1/calls/alerts/count"),
    markAlertSeen: (alertId: string) =>
      apiFetch<CallAlert>(`/api/v1/calls/alerts/${alertId}/seen`, { method: "POST" }),
    getPendingWrapups: () =>
      apiFetch<CallLog[]>(`/api/v1/calls/pending-wrapups`),
    pendingWrapupsSummary: () =>
      apiFetch<PendingWrapupSummary[]>(`/api/v1/calls/pending-wrapups/summary`),
    dismissFeedback: (callLogId: string, reason: string) =>
      apiFetch<{ dismissed: boolean }>(`/api/v1/calls/${callLogId}/dismiss-feedback`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    nextLead: (callerId?: string) =>
      apiFetch<Lead>(`/api/v1/calls/next-lead${callerId ? `?caller_id=${callerId}` : ""}`),
    assignmentMode: () =>
      apiFetch<{ mode: "push" | "pull"; enabled: boolean; calling_provider: "telecmi" | "sim_basic" }>(`/api/v1/calls/assignment-mode`),
    sendToMobile: (leadId: string, callerId?: string | null) =>
      apiFetch<{
        sent: boolean;
        lead_id: string;
        caller_id: string | null;
        push_url: string;
        push_configured: boolean;
        subscription_count: number;
      }>(`/api/v1/calls/send-to-mobile`, {
        method: "POST",
        body: JSON.stringify({ lead_id: leadId, caller_id: callerId || undefined }),
      }),
  },
  notes: {
    leadsWithActivity: () =>
      apiFetch<{ data: { id: string; name: string | null; phone: string; score: number; segment: string; assigned_to: string | null }[] }>(
        `/api/v1/lead-notes/leads-with-activity`
      ),
    all: () =>
      apiFetch<{ data: NoteWithLead[] }>(`/api/v1/lead-notes/all`),
    update: (noteId: string, data: { content?: string; is_pinned?: boolean; tags?: string[] }) =>
      apiFetch<{ id: string; content: string; is_pinned: boolean; tags: string[] }>(
        `/api/v1/lead-notes/note/${noteId}`,
        { method: "PATCH", body: JSON.stringify(data) }
      ),
    delete: (noteId: string) =>
      apiFetch<{ deleted: boolean }>(`/api/v1/lead-notes/note/${noteId}`, { method: "DELETE" }),
  },
  callReview: {
    leads: (range: ReviewRange) =>
      apiFetch<{ data: ReviewLead[]; truncated: boolean }>(`/api/v1/call-review/leads?${reviewQuery(range)}`),
    leadCalls: async (leadId: string, range: ReviewRange) => {
      const res = await apiFetch<{ data: CallLog[] }>(`/api/v1/call-review/leads/${leadId}/calls?${reviewQuery(range)}`);
      return res.data || [];
    },
  },
  segments: {
    templates: async () => {
      const res = await apiFetch<{ data: SegmentTemplate[] }>(`/api/v1/segments/templates`);
      return res.data || [];
    },
    saveTemplate: (segment: string, message: string, enabled = true) =>
      apiFetch<SegmentTemplate>(`/api/v1/segments/templates/${segment}`, {
        method: "PUT",
        body: JSON.stringify({ message, enabled }),
      }),
  },
  broadcasts: {
    history: async () => {
      const res = await apiFetch<{ data: BroadcastHistoryItem[] }>("/api/v1/upload/history");
      return res.data || [];
    },
  },
  reengagement: {
    listSteps: async (params?: { type?: string; broadcast_id?: string }) => {
      const qs = new URLSearchParams();
      if (params?.type) qs.set("type", params.type);
      if (params?.broadcast_id) qs.set("broadcast_id", params.broadcast_id);
      const res = await apiFetch<{ data: ReengagementStep[] }>(`/api/v1/reengagement/steps?${qs}`);
      return res.data || [];
    },
    createStep: (data: {
      type: "broadcast" | "inbound";
      broadcast_id?: string | null;
      delay_hours: number;
      target_segments: string[];
      target_sources?: string[] | null;
      message_type: "freeform" | "template";
      message_content?: string | null;
      template_name?: string | null;
      template_variables?: string[] | null;
      fallback_template_name?: string | null;
      fallback_template_variables?: string[] | null;
    }) =>
      apiFetch<ReengagementStep>(`/api/v1/reengagement/steps`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    updateStep: (
      stepId: string,
      data: {
        delay_hours: number;
        target_segments: string[];
        target_sources?: string[] | null;
        message_type: "freeform" | "template";
        message_content?: string | null;
        template_name?: string | null;
        template_variables?: string[] | null;
        fallback_template_name?: string | null;
        fallback_template_variables?: string[] | null;
      }
    ) =>
      apiFetch<ReengagementStep>(`/api/v1/reengagement/steps/${stepId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    deleteStep: (stepId: string) =>
      apiFetch<{ success: boolean }>(`/api/v1/reengagement/steps/${stepId}`, {
        method: "DELETE",
      }),
    getLogs: async (stepId?: string) => {
      const qs = stepId ? `?step_id=${stepId}` : "";
      const res = await apiFetch<{ data: ReengagementLog[] }>(`/api/v1/reengagement/logs${qs}`);
      return res.data || [];
    },
  },
  knowledge: {
    listDocuments: async () => {
      const res = await apiFetch<{ data: Array<{
        id: string;
        name: string;
        size_bytes: number;
        file_type: string;
        status: string;
        created_at: string;
        chunk_count?: number;
        error_message?: string | null;
        campaign_tag_id?: string | null;
        sorted_at?: string | null;
        sort_state?: "sorting" | "review" | "failed" | null;
        has_pending_review?: boolean;
        /** False when Aira can't run a vector search over this file. */
        searchable?: boolean;
        search_issue?: null | "no_jina_key" | "not_indexed";
      }> }>(`/api/v1/knowledge/documents`);
      return res.data || [];
    },
    uploadDocument: async (
      file: File,
      campaignTagId?: string | null,
      replacesDocumentId?: string | null,
    ) => {
      const authHeaders = await getAuthHeaders();
      const fd = new FormData();
      fd.append("file", file);
      if (campaignTagId) fd.append("campaign_tag_id", campaignTagId);
      if (replacesDocumentId) fd.append("replaces_document_id", replacesDocumentId);
      const res = await fetch(`${API_URL}/api/v1/knowledge/upload-document`, {
        method: "POST",
        body: fd,
        headers: { ...authHeaders },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(typeof err?.detail === "string" ? err.detail : "Upload failed");
      }
      return res.json();
    },
    /** With a body, lines the client edited are only removed when listed in remove_edited,
     *  and a Description that changed since the preview is refused (409). */
    deleteDocument: (id: string, body?: { base_version_id: string; remove_edited: string[] }) =>
      apiFetch<{ success: boolean; description_changed: boolean }>(`/api/v1/knowledge/documents/${id}`, {
        method: "DELETE",
        ...(body ? { body: JSON.stringify(body) } : {}),
      }),
    deletePreview: (id: string) =>
      apiFetch<KnowledgeDeletePreview>(`/api/v1/knowledge/documents/${id}/delete-preview`),
    /** Which of the 8 Business Kit headings Aira already has (no AI call). */
    readiness: () =>
      apiFetch<{ data: KnowledgeReadinessItem[] }>(`/api/v1/knowledge/readiness`),
    getReview: (id: string) =>
      apiFetch<KnowledgeReview>(`/api/v1/knowledge/documents/${id}/review`),
    applyReview: (id: string, choices: KnowledgeApplyChoices) =>
      apiFetch<{ success: boolean; description_changed: boolean; rubric_queued: boolean }>(
        `/api/v1/knowledge/documents/${id}/review/apply`,
        { method: "POST", body: JSON.stringify(choices) },
      ),
    discardReview: (id: string) =>
      apiFetch<{ success: boolean }>(`/api/v1/knowledge/documents/${id}/review/discard`, {
        method: "POST",
      }),
    resort: (id: string) =>
      apiFetch<{ success: boolean }>(`/api/v1/knowledge/documents/${id}/resort`, {
        method: "POST",
      }),
    updateFacts: (id: string, text: string) =>
      apiFetch<{ success: boolean; full_text: string }>(`/api/v1/knowledge/documents/${id}/facts`, {
        method: "PUT",
        body: JSON.stringify({ text }),
      }),
    listVersions: async (kind: "description" | "facts", documentId?: string) => {
      const qs = new URLSearchParams({ kind });
      if (documentId) qs.set("document_id", documentId);
      const res = await apiFetch<{ data: KnowledgeVersion[] }>(`/api/v1/knowledge/versions?${qs.toString()}`);
      return res.data || [];
    },
    restoreVersion: (versionId: string) =>
      apiFetch<{ success: boolean; kind: "description" | "facts" }>(
        `/api/v1/knowledge/versions/${versionId}/restore`,
        { method: "POST" },
      ),
    documentContent: (id: string) =>
      apiFetch<KnowledgeDocContent>(`/api/v1/knowledge/documents/${id}/content`),
    documentDownloadUrl: (id: string) =>
      apiFetch<{ url: string; name: string }>(`/api/v1/knowledge/documents/${id}/download`),
    listCampaignTags: async () => {
      const res = await apiFetch<{ data: Array<{ id: string; name: string; color?: string }> }>(`/api/v1/broadcast-tags/`);
      return res.data || [];
    },
  },
  catalog: {
    adjustStock: (
      itemId: string,
      data: { delta: number; reason: "restock" | "adjustment" | "return"; note?: string }
    ) =>
      apiFetch<{ ok: boolean; tracked: boolean; quantity_after: number | null }>(
        `/api/v1/catalog/items/${itemId}/stock`,
        { method: "POST", body: JSON.stringify(data) }
      ),
    stockMovements: async (itemId: string) => {
      const res = await apiFetch<{ data: StockMovement[] }>(`/api/v1/catalog/items/${itemId}/stock-movements`);
      return res.data || [];
    },
    listItems: async (q?: string) => {
      const qs = q ? `?q=${encodeURIComponent(q)}` : "";
      const res = await apiFetch<{ data: CatalogItem[] }>(`/api/v1/catalog/items${qs}`);
      return res.data || [];
    },
    createItem: (data: {
      name: string;
      item_type: string;
      description?: string | null;
      attributes?: Record<string, string>;
      variant_group_id?: string | null;
      price_paise?: number | null;
      price_note?: string | null;
      stock_quantity?: number | null;
      gst_rate?: number | null;
    }) =>
      apiFetch<CatalogItem>(`/api/v1/catalog/items`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    updateItem: (
      id: string,
      data: Partial<
        Pick<
          CatalogItem,
          | "name"
          | "item_type"
          | "description"
          | "status"
          | "attributes"
          | "variant_group_id"
          | "price_paise"
          | "price_note"
          | "stock_quantity"
          | "gst_rate"
        >
      >
    ) =>
      apiFetch<CatalogItem>(`/api/v1/catalog/items/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    deleteItem: (id: string) =>
      apiFetch<{ success: boolean }>(`/api/v1/catalog/items/${id}`, {
        method: "DELETE",
      }),
    uploadMedia: async (itemId: string, file: File, label?: string): Promise<CatalogMedia> => {
      const authHeaders = await getAuthHeaders();
      const fd = new FormData();
      fd.append("file", file);
      if (label) fd.append("label", label);
      const res = await fetch(`${API_URL}/api/v1/catalog/items/${itemId}/media`, {
        method: "POST",
        body: fd,
        headers: { ...authHeaders },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Media upload failed" }));
        throw new Error(err.detail || "Media upload failed");
      }
      return res.json();
    },
    listMedia: async () => {
      const res = await apiFetch<{ data: CatalogMedia[] }>(`/api/v1/catalog/media`);
      return res.data || [];
    },
    updateMedia: (id: string, data: { label?: string }) =>
      apiFetch<CatalogMedia>(`/api/v1/catalog/media/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    reorderMedia: (itemId: string, mediaIds: string[]) =>
      apiFetch<{ success: boolean }>(`/api/v1/catalog/items/${itemId}/media/reorder`, {
        method: "PATCH",
        body: JSON.stringify({ media_ids: mediaIds }),
      }),
    deleteMedia: (id: string) =>
      apiFetch<{ success: boolean }>(`/api/v1/catalog/media/${id}`, {
        method: "DELETE",
      }),
    getAiRules: () => apiFetch<CatalogAiRules>(`/api/v1/catalog/ai-rules`),
    updateAiRules: (data: Partial<Pick<CatalogAiRules, "can_recommend" | "can_send_images" | "max_images_per_reply">>) =>
      apiFetch<CatalogAiRules>(`/api/v1/catalog/ai-rules`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    listVariantGroups: async () => {
      const res = await apiFetch<{ data: CatalogVariantGroup[] }>(`/api/v1/catalog/variant-groups`);
      return res.data || [];
    },
    createVariantGroup: (data: { name: string; item_type?: string }) =>
      apiFetch<CatalogVariantGroup>(`/api/v1/catalog/variant-groups`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    reindex: () =>
      apiFetch<{ success: boolean; items_embedded: number; items_total: number }>(`/api/v1/catalog/reindex`, {
        method: "POST",
      }),
  },
  aiTune: {
    description: async () => {
      const res = await apiFetch<{ description: string }>(`/api/v1/ai-tune/description`);
      return res.description || "";
    },
    updateDescription: (description: string) =>
      apiFetch<{ description: string }>(`/api/v1/ai-tune/description`, {
        method: "PUT",
        body: JSON.stringify({ description }),
      }),
  },
  system: {
    status: () => apiFetch<SystemStatus>(`/api/v1/system/status`),
  },
  analytics: {
    overview: () => apiFetch<AnalyticsOverview>(`/api/v1/analytics/overview`),
    adPerformance: () => apiFetch<AdPerformanceSummary>(`/api/v1/analytics/ad-performance`),
    telecalling: () => apiFetch<TelecallingAnalytics>(`/api/v1/analytics/telecalling`),
    funnel: () => apiFetch<FunnelAnalytics>(`/api/v1/analytics/funnel`),
    overviewExtended: (range: "today" | "7d" | "30d" = "7d") =>
      apiFetch<AnalyticsOverviewExtended>(`/api/v1/analytics/overview?range=${range}`),
    messaging: (channel: string = "all", range: "today" | "7d" | "30d" = "7d") =>
      apiFetch<MessagingAnalytics>(`/api/v1/analytics/messaging?channel=${channel}&range=${range}`),
    telecallingExtended: (params?: { from?: string; to?: string }) => {
      const qs = new URLSearchParams();
      if (params?.from) qs.set("from", params.from);
      if (params?.to) qs.set("to", params.to);
      const s = qs.toString();
      return apiFetch<TelecallingAnalyticsExtended>(`/api/v1/analytics/telecalling${s ? `?${s}` : ""}`);
    },
    funnelExtended: () =>
      apiFetch<FunnelAnalyticsExtended>(`/api/v1/analytics/funnel`),
    templatePerformance: async (range: string) => {
      const res = await apiFetch<{ data: TemplatePerformanceRow[] }>(`/api/v1/analytics/template-performance?${range}`);
      return res.data || [];
    },
    inbound: (range: string) =>
      apiFetch<{
        kpis: {
          today: { total: number; organic: number; ad: number };
          range: { total: number; organic: number; ad: number };
        };
        daily: { day: string; organic: number; ad: number }[];
        by_segment: { A: number; B: number; C: number; D: number };
        by_channel: { whatsapp: number; instagram: number; facebook: number; telegram: number };
      }>(`/api/v1/analytics/inbound?range=${range}`),
    callerTimeline: (callerId: string, date: string) =>
      apiFetch<{ data: TimelineEvent[] }>(`/api/v1/analytics/caller-timeline?caller_id=${encodeURIComponent(callerId)}&date=${encodeURIComponent(date)}`),
    /** Scored calls in the window, lowest score first. */
    qaQueue: (params: { from: string; to: string; callerId?: string | null; page?: number; limit?: number }) => {
      const qs = new URLSearchParams({ from: params.from, to: params.to, page: String(params.page ?? 1), limit: String(params.limit ?? 10) });
      if (params.callerId) qs.set("caller_id", params.callerId);
      return apiFetch<{ data: CallLog[]; total: number; page: number; limit: number }>(`/api/v1/analytics/qa-queue?${qs.toString()}`);
    },
    compare: (params: CompareParams) => {
      const qs = new URLSearchParams({ preset: params.preset });
      if (params.start) qs.set("start", params.start);
      if (params.end) qs.set("end", params.end);
      qs.set("comparison", params.comparison);
      if (params.comparison === "custom") {
        qs.set("comparison_start", params.comparison_start);
        qs.set("comparison_end", params.comparison_end);
      }
      return apiFetch<ComparePayload>(`/api/v1/analytics/compare?${qs.toString()}`);
    },
    exportCompareCsv: async (params: CompareParams) => {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams({ preset: params.preset });
      if (params.start) qs.set("start", params.start);
      if (params.end) qs.set("end", params.end);
      qs.set("comparison", params.comparison);
      if (params.comparison === "custom") {
        qs.set("comparison_start", params.comparison_start);
        qs.set("comparison_end", params.comparison_end);
      }
      const res = await fetch(`${API_URL}/api/v1/analytics/compare/export?${qs.toString()}`, { headers });
      if (!res.ok) throw new Error(`Export failed: ${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "period_comparison.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
    exportTelecallingCsv: async (since?: string, until?: string) => {
      const headers = await getAuthHeaders();
      const qs = new URLSearchParams({ format: "csv" });
      if (since) qs.set("since", since);
      if (until) qs.set("until", until);
      const res = await fetch(`${API_URL}/api/v1/analytics/telecalling/export?${qs.toString()}`, { headers });
      if (!res.ok) throw new Error(`Export failed: ${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "telecalling_performance.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
  },
  insights: {
    whatsapp: (params?: { range?: string; since?: string; until?: string; source?: string }) => {
      const qs = new URLSearchParams();
      if (params?.range) qs.set("range", params.range);
      if (params?.since) qs.set("since", params.since);
      if (params?.until) qs.set("until", params.until);
      if (params?.source) qs.set("source", params.source);
      const q = qs.toString();
      return apiFetch(`/api/v1/insights/whatsapp${q ? `?${q}` : ""}`);
    },
    sync: () => apiFetch(`/api/v1/insights/sync`, { method: "POST" }),
    trends: (range = "30d") => apiFetch(`/api/v1/insights/trends?range=${range}`),
  },
  followUps: {
    summary: () => apiFetch<FollowUpSummary>(`/api/v1/follow-ups/summary`),
    run: (limit = 20) =>
      apiFetch<FollowUpRunResult>(`/api/v1/follow-ups/run?limit=${limit}`, {
        method: "POST",
      }),
    rescheduleCallback: (jobId: string, scheduledFor: string) =>
      apiFetch<{ success: boolean; data: unknown }>(`/api/v1/follow-ups/callback/${jobId}/reschedule`, {
        method: "PATCH",
        body: JSON.stringify({ scheduled_for: scheduledFor }),
      }),
    callbacksBoard: () =>
      apiFetch<{ data: CallbackBoardItem[] }>(`/api/v1/follow-ups/callbacks/board`),
  },
  settings: {
    getAiAutoReply: () =>
      apiFetch<{ enabled: boolean }>(`/api/v1/settings/ai-auto-reply`),
    getAutoReplySources: () =>
      apiFetch<{ sources: AutoReplySource[] }>(`/api/v1/settings/auto-reply-sources`),
    getTelecallingConfig: () =>
      apiFetch<TelecallingConfig>(`/api/v1/settings/telecalling-config`),
  },
  upload: {
    leads: async (
      file: File,
      options?: {
        campaignMessage?: string;
        segmentOverride?: string;
        platform?: string;
        campaignName?: string;
        externalCampaignId?: string;
        adSetName?: string;
        externalAdSetId?: string;
        adName?: string;
        externalAdId?: string;
        utmSource?: string;
        utmCampaign?: string;
        utmContent?: string;
        spendInr?: string;
      },
    ) => {
      const fd = new FormData();
      fd.append("file", file);
      if (options?.campaignMessage) fd.append("campaign_message", options.campaignMessage);
      if (options?.segmentOverride) fd.append("segment_override", options.segmentOverride);
      if (options?.platform) fd.append("platform", options.platform);
      if (options?.campaignName) fd.append("campaign_name", options.campaignName);
      if (options?.externalCampaignId) fd.append("external_campaign_id", options.externalCampaignId);
      if (options?.adSetName) fd.append("ad_set_name", options.adSetName);
      if (options?.externalAdSetId) fd.append("external_ad_set_id", options.externalAdSetId);
      if (options?.adName) fd.append("ad_name", options.adName);
      if (options?.externalAdId) fd.append("external_ad_id", options.externalAdId);
      if (options?.utmSource) fd.append("utm_source", options.utmSource);
      if (options?.utmCampaign) fd.append("utm_campaign", options.utmCampaign);
      if (options?.utmContent) fd.append("utm_content", options.utmContent);
      if (options?.spendInr) fd.append("spend_inr", options.spendInr);
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/leads`, { method: "POST", body: fd, headers: { ...authHeaders } });
      if (!res.ok) throw new Error(`Upload failed ${res.status}: ${await res.text()}`);
      return res.json() as Promise<{
        total: number;
        inserted: number;
        skipped: number;
        attributed: number;
        campaign_sent: number;
        campaign_failed: number;
      }>;
    },
  },
  onboarding: {
    status: () =>
      apiFetch<{ has_tenant: boolean; tenant_id?: string; role?: string }>("/api/v1/onboarding/status"),
    create: (name: string) =>
      apiFetch<{ tenant_id: string; already_exists: boolean }>("/api/v1/onboarding/", {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    starters: () =>
      apiFetch<{ data: VerticalStarter[] }>("/api/v1/onboarding/starters"),
    applyStarter: (key: string, force = false) =>
      apiFetch<{ applied: string }>("/api/v1/onboarding/apply-starter", {
        method: "POST",
        body: JSON.stringify({ key, force }),
      }),
    interviewQuestions: () =>
      apiFetch<{ data: InterviewQuestion[] }>("/api/v1/onboarding/interview/questions"),
    interviewDraft: (answers: { question_id: string; answer: string }[]) =>
      apiFetch<InterviewDraft>("/api/v1/onboarding/interview/draft", {
        method: "POST",
        body: JSON.stringify({ answers }),
      }),
    interviewApply: (draft: InterviewDraft, force = false) =>
      apiFetch<{ applied: boolean }>("/api/v1/onboarding/interview/apply", {
        method: "POST",
        body: JSON.stringify({ ...draft, force }),
      }),
  },
  operator: {
    getCallingProvider: (tenantId: string) =>
      apiFetch<{ tenant_id: string; calling_provider: "telecmi" | "sim_basic"; telecalling_enabled: boolean }>(
        `/api/v1/operator/clients/${tenantId}/calling-provider`
      ),
    updateCallingProvider: (tenantId: string, callingProvider: "telecmi" | "sim_basic") =>
      apiFetch<{ tenant_id: string; calling_provider: "telecmi" | "sim_basic" }>(
        `/api/v1/operator/clients/${tenantId}/calling-provider`,
        {
          method: "PATCH",
          body: JSON.stringify({ calling_provider: callingProvider }),
        }
      ),
  },
  team: {
    me: () => apiFetch<MyProfile>("/api/v1/team/me"),
    list: () => apiFetch<{ data: TeamMember[]; calling_provider?: "telecmi" | "sim_basic" }>("/api/v1/team/"),
    remove: (userId: string) =>
      apiFetch<{ removed: boolean }>(`/api/v1/team/${userId}`, { method: "DELETE" }),
    attendanceGrid: (params?: { month?: string; from?: string; to?: string }) => {
      const qs = new URLSearchParams();
      if (params?.month) qs.set("month", params.month);
      if (params?.from) qs.set("from", params.from);
      if (params?.to) qs.set("to", params.to);
      const s = qs.toString();
      return apiFetch<{ data: TeamAttendanceGridData }>(`/api/v1/team/attendance${s ? `?${s}` : ""}`);
    },
    attendanceForCaller: (callerId: string, months: number = 4) =>
      apiFetch<{ data: CallerAttendance }>(`/api/v1/team/attendance/${callerId}?months=${months}`),
    markAttendance: (callerId: string, date: string, status: "present" | "absent") =>
      apiFetch<{ data: AttendanceDay }>(`/api/v1/team/attendance/${callerId}`, {
        method: "POST",
        body: JSON.stringify({ date, status }),
      }),
    markHoliday: (date: string) =>
      apiFetch<{ data: { date: string; status: string; caller_count: number } }>("/api/v1/team/attendance/holiday", {
        method: "POST",
        body: JSON.stringify({ date }),
      }),
    updateShiftConfig: (config: { shift_mode: "common" | "individual"; shift_start_hour: number; shift_end_hour: number }) =>
      apiFetch<{ shift_mode: "common" | "individual"; shift_start_hour: number; shift_end_hour: number }>("/api/v1/team/shift-config", {
        method: "PATCH",
        body: JSON.stringify(config),
      }),
    updateCallerShift: (callerId: string, shift_start_hour: number, shift_end_hour: number) =>
      apiFetch<{ data: Caller }>(`/api/v1/team/${callerId}/shift`, {
        method: "PATCH",
        body: JSON.stringify({ shift_start_hour, shift_end_hour }),
      }),
  },
  rbac: {
    permissions: () =>
      apiFetch<{ data: PermissionDef[] }>("/api/v1/rbac/permissions"),
    roles: () =>
      apiFetch<{ data: ClientRole[]; permissions: PermissionDef[]; setup_required?: boolean; detail?: string }>("/api/v1/rbac/roles"),
    createRole: (data: { name: string; permissions: string[] }) =>
      apiFetch<ClientRole>("/api/v1/rbac/roles", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    updateRole: (id: string, data: { name: string; permissions: string[] }) =>
      apiFetch<ClientRole>(`/api/v1/rbac/roles/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    deleteRole: (id: string) =>
      apiFetch<{ deleted: boolean }>(`/api/v1/rbac/roles/${id}`, {
        method: "DELETE",
      }),
    users: () =>
      apiFetch<{ data: RbacUser[]; telecaller_seats?: { limit: number; used: number } }>("/api/v1/rbac/users"),
    createUser: (data: {
      full_name: string;
      email: string;
      role_id: string;
      temporary_password: string;
      phone?: string | null;
      telecmi_agent_id?: string | null;
      telecmi_agent_password?: string | null;
    }) =>
      apiFetch<{ created: boolean; user_id: string; temporary_password: string }>("/api/v1/rbac/users", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    updateUser: (userId: string, data: {
      full_name?: string;
      role_id?: string;
      phone?: string | null;
      telecmi_agent_id?: string | null;
      telecmi_agent_password?: string | null;
    }) =>
      apiFetch<{ updated: boolean }>(`/api/v1/rbac/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    deleteUser: (userId: string) =>
      apiFetch<{ deleted: boolean }>(`/api/v1/rbac/users/${userId}`, {
        method: "DELETE",
      }),
    auditLog: (params?: { page?: number; date_from?: string; date_to?: string }) => {
      const qs = new URLSearchParams();
      if (params?.page) qs.set("page", String(params.page));
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      const query = qs.toString();
      return apiFetch<{ data: AuditLogEntry[]; total: number; page: number; limit: number }>(
        `/api/v1/rbac/audit-log${query ? `?${query}` : ""}`,
      );
    },
    resetPassword: (userId: string) =>
      apiFetch<{ temporary_password: string }>(`/api/v1/rbac/users/${userId}/reset-password`, {
        method: "POST",
      }),
    markPasswordResetComplete: () =>
      apiFetch<{ updated: boolean }>("/api/v1/rbac/password-reset-complete", {
        method: "POST",
      }),
  },
  todos: {
    list: async (params?: { start_date?: string; end_date?: string }) => {
      const qs = new URLSearchParams();
      if (params?.start_date) qs.set("start_date", params.start_date);
      if (params?.end_date) qs.set("end_date", params.end_date);
      return apiFetch<Todo[]>(`/api/v1/todos/?${qs}`);
    },
    create: (data: { todo_date: string; content: string }) =>
      apiFetch<Todo>(`/api/v1/todos/`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    delete: (id: string) =>
      apiFetch<{ success: boolean }>(`/api/v1/todos/${id}`, {
        method: "DELETE",
      }),
    update: (id: string, data: { is_completed?: boolean; content?: string }) =>
      apiFetch<Todo>(`/api/v1/todos/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
  },
  inboundLeads: {
    /** currentAccount: only campaigns from the ad account connected now (the Meta Ads table's scope). */
    campaigns: async (opts?: { currentAccount?: boolean }) => {
      const res = await apiFetch<{ data: { id: string; campaign_name: string; platform: string; created_at?: string; meta_created_at?: string | null }[] }>(
        `/api/v1/inbound-leads/campaigns${opts?.currentAccount ? "?current_account=true" : ""}`
      );
      return res.data || [];
    },
    googleLink: async (campaign: string, gclid?: string) => {
      const qs = new URLSearchParams({ campaign });
      if (gclid) qs.set("gclid", gclid);
      return apiFetch<{ link: string; campaign_slug: string; whatsapp_number: string }>(
        `/api/v1/inbound-leads/google-link?${qs}`
      );
    },
    list: async (params?: {
      origin?: string;
      segment?: string;
      ad_campaign_id?: string;
      source?: string;
      date_from?: string;
      date_to?: string;
      page?: number;
      limit?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.origin) qs.set("origin", params.origin);
      if (params?.segment) qs.set("segment", params.segment);
      if (params?.ad_campaign_id) qs.set("ad_campaign_id", params.ad_campaign_id);
      if (params?.source) qs.set("source", params.source);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      if (params?.page) qs.set("page", String(params.page));
      if (params?.limit) qs.set("limit", String(params.limit));
      return apiFetch<{ data: InboundLead[]; total: number; page: number; limit: number }>(`/api/v1/inbound-leads/?${qs}`);
    },
    exportCsv: async (params?: {
      origin?: string;
      segment?: string;
      ad_campaign_id?: string;
      source?: string;
      date_from?: string;
      date_to?: string;
    }) => {
      const qs = new URLSearchParams();
      if (params?.origin) qs.set("origin", params.origin);
      if (params?.segment) qs.set("segment", params.segment);
      if (params?.ad_campaign_id) qs.set("ad_campaign_id", params.ad_campaign_id);
      if (params?.source) qs.set("source", params.source);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/inbound-leads/export?${qs}`, { headers });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "inbound_leads.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
    adFilters: async () => apiFetch<AdFilterTree>(`/api/v1/inbound-leads/ad-filters`),
    generateAdTrackingCode: async (payload: { ad_creative_id: string; message: string }) =>
      apiFetch<AdTrackingCodeResponse>(
        `/api/v1/inbound-leads/ad-tracking-code`,
        { method: "POST", body: JSON.stringify(payload) },
      ),
    adSyncNow: async () =>
      apiFetch<{
        ok: boolean;
        error: string | null;
        rows_fetched: number;
        whatsapp_rows: number;
        skipped_non_whatsapp: number;
        account_id: string | null;
        written: number;
      }>(
        `/api/v1/inbound-leads/ad-sync-now`,
        { method: "POST" },
      ),
    adPerformance: async (params?: AdPerformanceParams) => {
      const qs = new URLSearchParams();
      if (params?.campaign_id) qs.set("campaign_id", params.campaign_id);
      if (params?.adset_id) qs.set("adset_id", params.adset_id);
      if (params?.ad_creative_id) qs.set("ad_creative_id", params.ad_creative_id);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      return apiFetch<{ data: AdPerformanceRow[] }>(`/api/v1/inbound-leads/ad-performance?${qs}`);
    },
    /** Meta's de-duplicated reach across these ads; null when Meta can't answer. */
    adPerformanceTotalReach: async (params: { ad_creative_ids: string[]; date_from?: string; date_to?: string }) => {
      const qs = new URLSearchParams({ ad_creative_ids: params.ad_creative_ids.join(",") });
      if (params.date_from) qs.set("date_from", params.date_from);
      if (params.date_to) qs.set("date_to", params.date_to);
      return apiFetch<{ reach: number | null }>(`/api/v1/inbound-leads/ad-performance/total-reach?${qs}`);
    },
    getMetaFieldCatalog: async () =>
      apiFetch<MetaFieldCatalog>(`/api/v1/inbound-leads/meta-ads/field-catalog`),
    getAllMetaAds: async (params: AllAdsParams) => {
      const qs = new URLSearchParams();
      if (params.date_from) qs.set("date_from", params.date_from);
      if (params.date_to) qs.set("date_to", params.date_to);
      if (params.fields.length) qs.set("fields", params.fields.join(","));
      if (params.breakdown) qs.set("breakdown", params.breakdown);
      if (params.refresh) qs.set("refresh", "true");
      return apiFetch<AllAdsResponse>(`/api/v1/inbound-leads/meta-ads/all-ads?${qs}`);
    },
    /** Meta's de-duplicated reach per campaign or ad set ({id: reach}); null when Meta can't answer. */
    getReachByLevel: async (params: { level: "campaign" | "adset"; meta_ad_ids?: string[]; date_from: string; date_to: string }) => {
      const qs = new URLSearchParams({ level: params.level, date_from: params.date_from, date_to: params.date_to });
      if (params.meta_ad_ids) qs.set("meta_ad_ids", params.meta_ad_ids.join(","));
      return apiFetch<{ reach: Record<string, number> | null }>(`/api/v1/inbound-leads/meta-ads/reach-by-level?${qs}`);
    },
    /** De-duplicated reach for the All ads Total row; omit ids for the whole account. */
    getAllAdsTotalReach: async (params: { meta_ad_ids?: string[]; date_from: string; date_to: string }) => {
      const qs = new URLSearchParams({ date_from: params.date_from, date_to: params.date_to });
      if (params.meta_ad_ids) qs.set("meta_ad_ids", params.meta_ad_ids.join(","));
      return apiFetch<{ reach: number | null }>(`/api/v1/inbound-leads/meta-ads/all-ads/total-reach?${qs}`);
    },
    getTrackedAds: async () =>
      apiFetch<{ data: TrackedAd[] }>(`/api/v1/inbound-leads/meta-ads/tracked-ads`),
    setCreativeTracking: async (adCreativeId: string, tracked: boolean) =>
      apiFetch<{ ad_creative_id: string; tracked: boolean }>(
        `/api/v1/inbound-leads/ad-creatives/${encodeURIComponent(adCreativeId)}/tracking`,
        { method: "PATCH", body: JSON.stringify({ tracked }) },
      ),
    getAdBreakdown: async (
      adCreativeId: string,
      params: { breakdown: AdBreakdownKey; date_from?: string; date_to?: string },
    ) => {
      const qs = new URLSearchParams();
      qs.set("breakdown", params.breakdown);
      if (params.date_from) qs.set("date_from", params.date_from);
      if (params.date_to) qs.set("date_to", params.date_to);
      return apiFetch<AdBreakdownResponse>(
        `/api/v1/inbound-leads/ad-creatives/${encodeURIComponent(adCreativeId)}/breakdown?${qs}`,
      );
    },
    getSyncStart: async () =>
      apiFetch<SyncStartInfo>(`/api/v1/inbound-leads/meta-ads/sync-start`),
    setSyncStart: async (startDate: string) =>
      apiFetch<SyncStartInfo>(
        `/api/v1/inbound-leads/meta-ads/sync-start`,
        { method: "PUT", body: JSON.stringify({ start_date: startDate }) },
      ),
    adPerformanceExportCsv: async (params?: AdPerformanceParams) => {
      const qs = new URLSearchParams();
      if (params?.campaign_id) qs.set("campaign_id", params.campaign_id);
      if (params?.adset_id) qs.set("adset_id", params.adset_id);
      if (params?.ad_creative_id) qs.set("ad_creative_id", params.ad_creative_id);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to) qs.set("date_to", params.date_to);
      if (params?.delivery_status) qs.set("delivery_status", params.delivery_status);
      const headers = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/inbound-leads/ad-performance/export?${qs}`, { headers });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "ad_performance.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    },
  },
  templates: {
    list: async () => {
      const res = await apiFetch<{ data: WabaTemplate[] }>("/api/v1/templates/");
      return res.data || [];
    },
  },
  autoMessages: {
    setup: () => apiFetch<AutoMessageSetup>("/api/v1/auto-messages/setup"),
    rotateToken: () => apiFetch<AutoMessageSetup>("/api/v1/auto-messages/setup/token", { method: "POST" }),
    events: () => apiFetch<AutoMessageEvents>("/api/v1/auto-messages/events"),
    createEvent: (data: { label: string; description?: string }) =>
      apiFetch<AutoMessageCustomEvent>("/api/v1/auto-messages/events", { method: "POST", body: JSON.stringify(data) }),
    updateEvent: (key: string, data: { label?: string; description?: string }) =>
      apiFetch<AutoMessageCustomEvent>(`/api/v1/auto-messages/events/${encodeURIComponent(key)}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    deleteEvent: (key: string) =>
      apiFetch<{ deleted: boolean }>(`/api/v1/auto-messages/events/${encodeURIComponent(key)}`, { method: "DELETE" }),
    rules: () => apiFetch<{ rules: AutoMessageRule[] }>("/api/v1/auto-messages/rules"),
    createRule: (data: Omit<AutoMessageRuleRow, "id" | "created_at">) =>
      apiFetch<AutoMessageRuleRow>("/api/v1/auto-messages/rules", { method: "POST", body: JSON.stringify(data) }),
    updateRule: (id: string, data: Partial<Omit<AutoMessageRuleRow, "id" | "created_at" | "event">>) =>
      apiFetch<AutoMessageRuleRow>(`/api/v1/auto-messages/rules/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    deleteRule: (id: string) =>
      apiFetch<{ deleted: boolean }>(`/api/v1/auto-messages/rules/${id}`, { method: "DELETE" }),
    previewRule: (id: string, phone: string) =>
      apiFetch<AutoMessagePreviewResult>(`/api/v1/auto-messages/rules/${id}/preview`, {
        method: "POST",
        body: JSON.stringify({ phone }),
      }),
    templates: () => apiFetch<{ templates: AutoMessageTemplate[] }>("/api/v1/auto-messages/templates"),
    summary: () => apiFetch<AutoMessageSummary>("/api/v1/auto-messages/summary"),
    sends: (params: { status?: string; event?: string; limit?: number; offset?: number } = {}) => {
      const q = new URLSearchParams();
      if (params.status) q.set("status", params.status);
      if (params.event) q.set("event", params.event);
      q.set("limit", String(params.limit ?? 10));
      q.set("offset", String(params.offset ?? 0));
      return apiFetch<AutoMessageSendsPage>(`/api/v1/auto-messages/sends?${q.toString()}`);
    },
    privateSend: () => apiFetch<PrivateSendStatus>("/api/v1/auto-messages/private-send"),
  },
  instantForms: {
    status: () => apiFetch<InstantFormsStatus>("/api/v1/instant-forms/status"),
    /** Subscribe the Page to new leads, copy its forms, import past leads in the background. */
    connect: () => apiFetch<{ forms: number; importing: boolean }>("/api/v1/instant-forms/connect", { method: "POST" }),
    /** Re-read the forms and pick up any lead from the last two days. */
    sync: () => apiFetch<{ forms: number }>("/api/v1/instant-forms/sync", { method: "POST" }),
    overview: (range: InstantFormRange) =>
      apiFetch<InstantFormsOverview>(`/api/v1/instant-forms/overview${instantFormsQuery(range)}`),
    form: (formId: string, range: InstantFormRange) =>
      apiFetch<InstantFormDetail>(`/api/v1/instant-forms/forms/${encodeURIComponent(formId)}${instantFormsQuery(range)}`),
    leads: (formId: string, params: InstantFormRange & { search?: string; page?: number; limit?: number }) =>
      apiFetch<InstantFormLeadsResponse>(
        `/api/v1/instant-forms/forms/${encodeURIComponent(formId)}/leads${instantFormsQuery(params)}`,
      ),
    templates: () => apiFetch<{ data: InstantFormTemplateOption[] }>("/api/v1/instant-forms/templates"),
    setTemplate: (formId: string, templateId: string | null, variables: InstantFormVariable[]) =>
      apiFetch<{ template_id: string | null; template_variables: InstantFormVariable[] }>(
        `/api/v1/instant-forms/forms/${encodeURIComponent(formId)}/template`,
        { method: "PUT", body: JSON.stringify({ template_id: templateId, variables }) },
      ),
    /** Send, or retry, the form's template to one lead. */
    sendTemplate: (rowId: string) =>
      apiFetch<{ status: string; template_status: InstantFormTemplateStatus; template_error: string | null }>(
        `/api/v1/instant-forms/leads/${encodeURIComponent(rowId)}/send-template`,
        { method: "POST" },
      ),
    /** Every lead on the form, read live from Meta, saved as a CSV laid out like Ads Manager's. */
    downloadFormLeads: (formId: string, formName: string) =>
      downloadCsv(
        `/api/v1/instant-forms/forms/${encodeURIComponent(formId)}/download`,
        `${formName.replace(/[\\/:*?"<>|]/g, "_").trim() || "form"}_Leads_${new Date().toISOString().slice(0, 10)}.csv`,
      ),
    /** Leads from these ads in the chosen dates, read live from Meta. */
    downloadAdLeads: (adIds: string[], range: { date_from: string; date_to: string }) =>
      downloadCsv(
        `/api/v1/instant-forms/ads/download?${new URLSearchParams({ ad_ids: adIds.join(","), ...range })}`,
        `leads_${range.date_from}_${range.date_to}.csv`,
      ),
  },
  marketplace: {
    status: () => apiFetch<Record<"indiamart" | "justdial", MarketplaceStatus>>("/api/v1/marketplace/status"),
    getWelcomeTemplate: () => apiFetch<{ template_id: string | null }>("/api/v1/marketplace/welcome-template"),
    setWelcomeTemplate: (templateId: string | null) =>
      apiFetch<{ template_id: string | null }>("/api/v1/marketplace/welcome-template", {
        method: "PUT",
        body: JSON.stringify({ template_id: templateId ?? "" }),
      }),
  },
  notifications: {
    list: () => apiFetch<{ data: AppNotification[] }>("/api/v1/notifications"),
    pool: () => apiFetch<{ data: PoolItem[] }>("/api/v1/notifications/pool"),
    markRead: (id: string) =>
      apiFetch<{ success: boolean; data: AppNotification }>(`/api/v1/notifications/${id}/read`, {
        method: "PATCH",
      }),
    markAllRead: () =>
      apiFetch<{ success: boolean }>("/api/v1/notifications/read", {
        method: "PATCH",
      }),
    getConfig: () => apiFetch<NotificationConfig>("/api/v1/notifications/config"),
    saveConfig: (config: NotificationConfig) =>
      apiFetch<NotificationConfig>("/api/v1/notifications/config", {
        method: "PUT",
        body: JSON.stringify(config),
      }),
  },
  push: {
    publicKey: () => apiFetch<{ public_key: string | null }>("/api/v1/push/public-key"),
    status: () => apiFetch<{ supported_by_server: boolean; public_key_configured: boolean; private_key_configured: boolean; subscription_count: number }>("/api/v1/push/status"),
    saveSubscription: (subscription: PushSubscriptionJSON) =>
      apiFetch<{ saved: boolean }>("/api/v1/push/subscriptions", {
        method: "POST",
        body: JSON.stringify(subscription),
      }),
    deleteSubscription: (endpoint: string) =>
      apiFetch<{ deleted: boolean }>(`/api/v1/push/subscriptions?endpoint=${encodeURIComponent(endpoint)}`, {
        method: "DELETE",
      }),
  },
  chatHandovers: {
    count: (todayOnly?: boolean) =>
      apiFetch<{ count: number }>(
        `/api/v1/chat-handovers/count${todayOnly ? "?today_only=true" : ""}`
      ),
    assign: (handoverId: string, callerId: string) =>
      apiFetch<{ assigned: boolean }>(`/api/v1/chat-handovers/${handoverId}/assign`, {
        method: "PATCH",
        body: JSON.stringify({ caller_id: callerId }),
      }),
  },
  deals: {
    list: (
      filters: DealFilters = {},
      opts: { sort?: DealSort; dir?: "asc" | "desc"; page?: number; limit?: number } = {}
    ) => {
      const search = dealFilterParams(filters);
      if (filters.stage) search.set("stage", filters.stage);
      if (opts.sort) search.set("sort", opts.sort);
      if (opts.dir) search.set("dir", opts.dir);
      if (opts.page) search.set("page", String(opts.page));
      search.set("limit", String(opts.limit ?? 50));
      return apiFetch<DealListPage>(`/api/v1/deals?${search}`);
    },
    summary: (filters: Omit<DealFilters, "stage"> = {}) =>
      apiFetch<DealSummaryStats>(`/api/v1/deals/summary?${dealFilterParams(filters)}`),
    get: (dealId: string) => apiFetch<Deal>(`/api/v1/deals/${dealId}`),
    create: (payload: NewDealPayload) =>
      apiFetch<DealMutationResult>("/api/v1/deals", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    updateStage: (
      dealId: string,
      data: { stage: "won" | "lost"; payment_method?: PaymentMethod; lost_reason?: string }
    ) =>
      apiFetch<DealMutationResult>(`/api/v1/deals/${dealId}/stage`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    sendLink: (dealId: string) =>
      apiFetch<{ payment_link: string | null; message_sent: boolean }>(`/api/v1/deals/${dealId}/send-link`, {
        method: "POST",
      }),
    byLead: async (leadId: string) => {
      const res = await apiFetch<{ data: DealSummary[] }>(`/api/v1/deals/by-lead/${leadId}`);
      return res.data || [];
    },
    stats: (month: string, sources?: DealSource[]) =>
      apiFetch<DealStats>(
        `/api/v1/deals/stats?month=${encodeURIComponent(month)}${
          sources && sources.length > 0 ? `&source=${encodeURIComponent(sources.join(","))}` : ""
        }`
      ),
    activeMonths: () => apiFetch<{ months: string[] }>("/api/v1/deals/active-months"),
    // Downloaded with a raw fetch + blob (auth header needed), same as intake.csvPath.
    exportPath: (month: string, format: "xlsx" | "csv" = "xlsx") =>
      `/api/v1/deals/export?month=${encodeURIComponent(month)}&format=${format}`,
  },

  businessProfile: {
    get: () => apiFetch<BusinessProfile>("/api/v1/business-details"),
    save: (data: BusinessProfile) =>
      apiFetch<BusinessProfile>("/api/v1/business-details", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },

  intake: {
    listSessions: (params: {
      status: IntakeStatus | "all";
      packageKey?: string;
      q?: string;
      cursor?: string;
    }) => {
      const search = new URLSearchParams({ status: params.status, limit: "50" });
      if (params.packageKey) search.set("package", params.packageKey);
      if (params.q) search.set("q", params.q);
      if (params.cursor) search.set("cursor", params.cursor);
      return apiFetch<IntakePage>(`/api/v1/intake/sessions?${search}`);
    },
    changePackage: (sessionId: string, packageKey: string) =>
      apiFetch<IntakeSession>(`/api/v1/intake/sessions/${sessionId}/package`, {
        method: "PATCH",
        body: JSON.stringify({ package_key: packageKey }),
      }),
    stats: () => apiFetch<IntakeStats>("/api/v1/intake/stats"),
    csvPath: (params: { status: IntakeStatus | "all"; packageKey?: string; q?: string }) => {
      const search = new URLSearchParams({ status: params.status });
      if (params.packageKey) search.set("package", params.packageKey);
      if (params.q) search.set("q", params.q);
      return `/api/v1/intake/sessions.csv?${search}`;
    },
  },
};

export interface Todo {
  id: string;
  todo_date: string;
  content: string;
  is_completed: boolean;
  created_at: string;
  updated_at: string;
}

export interface InboundLead {
  id: string;
  phone: string;
  name: string;
  source: string;
  origin: string;
  channel_label: string;
  score: number;
  segment: string;
  segment_label: string;
  created_at: string;
  ad_campaign_id: string | null;
  campaign_name: string;
  campaign_platform: string;
  keyword: string;
}

export interface AdPerformanceRow {
  ad_creative_id: string;
  creative_label: string;
  meta_ad_id: string;
  meta_ad_account_id: string;
  adset_id: string | null;
  adset_name: string | null;
  campaign_id: string | null;
  /** Meta's campaign id: the Campaigns view groups by it. */
  meta_campaign_id?: string | null;
  campaign_name: string;
  /** The ad's own Meta effective_status (ACTIVE / PAUSED / DELETED / ...), falling
   * back to the campaign's or ad set's for rows synced before it was tracked. */
  delivery_status: string | null;
  /** Last day the ad was shown (YYYY-MM-DD), any date range. Sent for ACTIVE ads only; null there = never delivered. */
  last_delivery_date?: string | null;
  /** When the campaign was created in Meta Ads Manager; null until the next sync stores it. */
  campaign_created_at?: string | null;
  last_significant_edit?: string | null;
  schedule_start?: string | null;
  schedule_end?: string | null;
  /** Meta destination type (WHATSAPP, MESSENGER, INSTAGRAM_DIRECT, WEBSITE, ON_AD, ...). */
  destination_type?: string | null;
  /** True when the ad opens more than one chat app (e.g. WhatsApp plus Messenger). */
  is_multi_destination?: boolean;
  /** Chat apps this ad opens, in order: "whatsapp", "instagram", "messenger". */
  messaging_channels?: string[];
  /** Unique people who messaged from this ad, split by app. `messages` stays the total. */
  messages_by_channel?: { whatsapp: number; instagram: number; messenger: number };
  daily_budget: number | null;
  lifetime_budget: number | null;
  budget_level: "campaign" | "ad_set" | null;
  impressions: number;
  reach: number;
  /** Meta didn't return its de-duplicated reach, so `reach` is the daily figures added up. */
  reach_estimated?: boolean;
  frequency: number | null;
  inline_link_clicks: number;
  clicks_all: number;
  messages: number;
  meta_conversations: number;
  meta_conversations_started: number;
  meta_new_contacts: number;
  meta_conversations_replied: number;
  meta_blocks: number;
  cost_per_meta_conversation: number | null;
  cost_per_messaging_contact: number | null;
  cost_per_new_messaging_contact: number | null;
  conversation_rate: number | null;
  meta_conversation_rate: number | null;
  messaging_reply_rate: number | null;
  messaging_block_rate: number | null;
  meta_anril_contact_match_rate: number | null;
  attribution_gap: number;
  clicked_no_message: number;
  no_message_rate: number | null;
  hot: number;
  hot_rate: number | null;
  spend: number;
  cpc: number | null;
  cost_per_message: number | null;
  ctr: number | null;
  cpm: number | null;
  cost_per_hot: number | null;
}

export interface AdFilterTree {
  campaigns: { id: string; name: string }[];
  adsets: { id: string; name: string; campaign_id: string | null }[];
  creatives: {
    id: string;
    name: string;
    meta_ad_id: string | null;
    tracking_code: string | null;
    messaging_channels?: string[];
    adset_id: string | null;
    campaign_id: string | null;
  }[];
  account_id: string | null;
}

export interface AdTrackingCodeResponse {
  code: string;
  prefilled_message: string;
  ad_creative_id: string;
  creative_name: string;
  meta_ad_id: string;
}

export interface AdPerformanceParams {
  campaign_id?: string;
  adset_id?: string;
  ad_creative_id?: string;
  date_from?: string;
  date_to?: string;
  /** One of the DELIVERY_GROUPS keys in ad_performance.py: active, paused,
   * archived, deleted, removed, issues. Omit for all statuses. */
  delivery_status?: string;
}

export interface MetaField {
  key: string;
  label: string;
  group: string;
  format: "number" | "money" | "percent" | "decimal" | "text" | "date" | "image";
  breakdown_ok: boolean;
}

export interface MetaBreakdown {
  key: string;
  label: string;
}

// ── Meta Instant Forms (lead ads) ──────────────────────────────────────────

/** "ready": forms can be read. "needs_permission": Meta hasn't granted leads_retrieval /
 * pages_manage_ads to Anril yet, or the Page was connected before they were added. */
export type InstantFormsState = "no_page" | "needs_permission" | "needs_reconnect" | "error" | "ready";

export interface InstantFormsStatus {
  state: InstantFormsState;
  page_id: string | null;
  /** Meta sends new leads to Anril the moment they're submitted. */
  subscribed: boolean;
  message: string | null;
  forms: number;
}

export interface InstantFormStats {
  leads: number;
  with_phone: number;
  template_sent: number;
  template_failed: number;
  /** Wrote back on WhatsApp after the template. */
  replied: number;
  from_ads: number;
  /** Live from Meta for the ads that brought these leads; null when Meta can't say. */
  spend: number | null;
  cost_per_lead: number | null;
}

export interface InstantFormSummary extends InstantFormStats {
  form_id: string;
  name: string;
  status: string | null;
  created_at: string | null;
  questions: number;
  /** Ads that use this form, running ones first. */
  ad_names?: string[];
  /** For a form no ad uses now: the ads its leads came from, newest first. */
  past_ad_names?: string[];
  template_id: string | null;
  template_name: string | null;
  last_lead_at: string | null;
}

export interface InstantFormsOverview {
  date_from: string;
  date_to: string;
  spend_available: boolean;
  totals: InstantFormStats;
  forms: InstantFormSummary[];
}

export interface InstantFormQuestion {
  key: string;
  label: string | null;
  type: string | null;
}

export type InstantFormVariable =
  | { source: "field"; field: string }
  | { source: "text"; text: string };

export interface InstantFormDetail {
  form_id: string;
  name: string;
  status: string | null;
  locale: string | null;
  created_at: string | null;
  synced_at: string | null;
  questions: InstantFormQuestion[];
  template_id: string | null;
  template_variables: InstantFormVariable[];
  date_from: string;
  date_to: string;
  spend_available: boolean;
  stats: InstantFormStats;
}

export type InstantFormTemplateStatus =
  | "pending" | "sending" | "sent" | "failed" | "no_template" | "no_phone" | "skipped_old";

export interface InstantFormLead {
  id: string;
  leadgen_id: string;
  meta_created_at: string;
  name: string | null;
  phone: string | null;
  email: string | null;
  /** Meta's field_data: one entry per question, keyed by question key. */
  answers: { name: string; values: string[] }[];
  ad_id: string | null;
  ad_name: string | null;
  adset_name: string | null;
  campaign_name: string | null;
  platform: string | null;
  is_organic: boolean;
  /** The Anril lead it became; null for leads imported from before the connection. */
  lead_id: string | null;
  received_via: "webhook" | "catch_up" | "import";
  template_status: InstantFormTemplateStatus;
  template_error: string | null;
  template_sent_at: string | null;
  replied: boolean;
}

export interface InstantFormLeadsResponse {
  data: InstantFormLead[];
  total: number;
  page: number;
  limit: number;
}

export interface InstantFormTemplateOption {
  id: string;
  name: string;
  language: string;
  body_text: string;
  /** Number of {{n}} blanks in the body. */
  blanks: number;
  /** IMAGE / VIDEO / DOCUMENT header sent with the file saved on the template; null = no media. */
  header_media_type: "IMAGE" | "VIDEO" | "DOCUMENT" | "TEXT" | null;
  header_media_url: string | null;
  header_text: string | null;
}

export interface InstantFormRange {
  date_from?: string;
  date_to?: string;
}

export interface MetaFieldCatalog {
  fields: MetaField[];
  breakdowns: MetaBreakdown[];
}

export interface AllAdsRow {
  meta_ad_id: string;
  /** Meta's campaign / ad set ids: the Campaigns and Ad sets views group by them. */
  campaign_id?: string | null;
  adset_id?: string | null;
  ad_name: string;
  adset_name: string;
  campaign_name: string;
  destination_type: string | null;
  ad_type: string;
  breakdown: string | null;
  values: Record<string, unknown>;
}

export interface AllAdsResponse {
  data: AllAdsRow[];
  start_date: string | null;
  date_from: string;
  date_to: string;
}

export interface AllAdsParams {
  date_from?: string;
  date_to?: string;
  fields: string[];
  breakdown?: string;
  /** Skip the server's few-minute cache (Sync now). */
  refresh?: boolean;
}

export interface TrackedAd {
  ad_creative_id: string;
  creative_label: string;
  campaign_name: string;
  adset_name: string;
  delivery_status: string | null;
  destination_type: string | null;
  is_multi_destination: boolean;
  /** Chat apps this ad opens: "whatsapp", "instagram", "messenger". */
  messaging_channels?: string[];
  tracked: boolean;
}

export type AdBreakdownKey = "placement" | "age" | "gender" | "region" | "device";
export interface AdBreakdownValues {
  inline_link_clicks: number | null;
  spend: number | null;
  cost_per_inline_link_click: number | null;
  impressions: number | null;
  inline_link_click_ctr: number | null;
}
export interface AdBreakdownResponse {
  ad_creative_id: string;
  breakdown: AdBreakdownKey;
  date_from: string;
  date_to: string;
  start_date: string | null;
  overall: AdBreakdownValues | null;
  rows: { label: string; values: AdBreakdownValues }[];
}

export interface SyncStartInfo {
  start_date: string | null;
  connected_at: string | null;
  backfilled_from: string | null;
  earliest_ad_start: string | null;
  /** When the account last synced with Meta (ISO), for the "Last synced" note. */
  last_synced_at?: string | null;
  max_history_days: number;
  /** Only present on the response to PUT. */
  syncing?: boolean;
}

export { API_URL };

function instantFormsQuery(params: InstantFormRange & { search?: string; page?: number; limit?: number }): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

// ---------------------------------------------------------------------------
// Anril Agents (companion characters). Backend: routes/companions.py, behind
// companions.manage. Example: a business's "Maya" support character.
// ---------------------------------------------------------------------------

export type CompanionMood = "calm" | "warm" | "happy" | "concerned" | "encouraging" | "serious";
export type CompanionStatus = "draft" | "live" | "paused";

export interface Companion {
  id: string;
  name: string;
  industry: "astrology" | "general";
  role: string;
  backstory: string;
  speaking_style: string;
  sample_lines: string[];
  goals: string[];
  temperament: string;
  default_mood: CompanionMood;
  language: string;
  /**
   * The AI model every reply from this character uses, e.g. "google/gemini-3.1-flash-lite".
   * The label to show comes from companionsApi.models().
   */
  model: string;
  rules: string[];
  knowledge_tag_id: string | null;
  /** The collection of books this character reads (Anril Agents knowledge base). */
  knowledge_collection_id?: string | null;
  /** True: when no book covers the question, the character may answer from its own general knowledge and says it is its own reading. False: it says its material does not cover this. */
  own_reasoning?: boolean;
  memory_level: 1 | 2;
  memory_engine: "card" | "mem0";
  history_messages: number;
  privacy_mode: "A" | "B";
  status: CompanionStatus;
  /** Set when the owner archived it (Archived tab). Null = active. */
  archived_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export type CompanionInput = Partial<Omit<Companion, "id" | "created_at" | "updated_at" | "archived_at">>;

export interface CompanionApiKey {
  id: string;
  key_prefix: string;
  status: "active" | "revoked";
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
}

export interface CompanionInstall {
  companion_id: string;
  status: CompanionStatus;
  widget_script_url: string;
  api_base: string;
  has_active_key: boolean;
  snippets: { html: string; python: string; node: string; curl: string };
}

/** A tool the business's own app runs, e.g. a business's get_account. Sent with each message, never stored. */
export interface CompanionAppTool {
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
}

export interface CompanionToolCall {
  id: string;
  name: string;
  args?: Record<string, unknown>;
}

export interface CompanionReply {
  status: "done" | "tool_call";
  text: string | null;
  mood: string | null;
  turn_id: string | null;
  tool_calls: CompanionToolCall[];
  conversation_id: string | null;
  message_id: string | null;
  /** The model that answered (test chat only). */
  model?: string | null;
  /** Where the answer came from. Missing is the same as null. */
  basis?: "primary" | "book" | "own" | "chat" | null;
  /** The passages the answer relied on. Missing is the same as []. */
  sources?: { document: string; page_from: number; page_to: number }[];
  /** What was searched for this reply, one plain line per step (test chat only). Example: "Memory card: 6 lines". */
  trace?: string[];
  /** Where this test customer's memory stands after the reply (test chat only). */
  memory?: CompanionMemoryStatus;
}

/**
 * How close a test customer is to the next memory save. Example: Level 2, 3 unread of 8 ->
 * { level: 2, unread: 3, saves_at: 8 }. Level 1 characters keep recent chat only.
 */
export interface CompanionMemoryStatus {
  level: 1 | 2;
  unread: number;
  saves_at: number;
}

/**
 * A made-up customer the owner chats as in the Playground. "You" is always first.
 * Example: { external_user_id: "owner-test:u1:t4k9xz", name: "Asha", is_you: false }.
 */
export interface TestPerson {
  external_user_id: string;
  name: string;
  is_you: boolean;
}

/** What "Save now" did. saved = facts written; nothing_new = no unread messages; busy = a save was already running; waiting = the last reply is still being written. */
export type SaveMemoryOutcome = "saved" | "nothing_new" | "busy" | "waiting";

export interface CompanionMemoryFact {
  id: string;
  section: "profile" | "people" | "life" | "preferences" | "threads";
  text: string;
  valid_from: string | null;
  valid_to: string | null;
  status: "active" | "closed";
  learned_by: string;
}

export type CompanionMemoryScope = "character" | "business";

/** The Diary tab: the "earlier today" note and one line per past day (newest first). */
export interface CompanionDiary {
  today: { day: string | null; text: string } | null;
  days: { day: string; text: string }[];
}

export interface CompanionOverview {
  characters: number;
  live_characters: number;
  /** Real people, not Playground test chats or forgotten people. */
  people: number;
  messages_this_week: number;
  active_keys: number;
  key_last_used_at: string | null;
  model: string | null;
  /** Model and its provider's API key are both set, so characters can answer. */
  model_ready: boolean;
}

export interface CompanionPerson {
  external_user_id: string;
  /** For a Playground test customer: the name the owner typed; null for "You". */
  display_name: string | null;
  /** A Playground test customer (the Memories page tags it "Playground"). */
  is_test: boolean;
  /** null when the character is in privacy mode B. */
  fact_count: number | null;
  message_count: number;
  last_seen_at: string;
}

/** An error from the API with its HTTP status (409 duplicate name, 422 bad field, ...). */
export type ApiError = Error & { status?: number; detail?: unknown };

export type CompanionModel = { id: string; label: string };

/** Where a Playground search or chat looks. */
export type PlaygroundSources = "all" | "memories" | "knowledge";

/**
 * The Playground's search and memory settings, sent with test chats and searches.
 * A field left out means "what live chat does". Example: { memory_floor: 0.6, rerank: false }.
 */
export type PlaygroundSettings = {
  sources?: PlaygroundSources;
  /** 1 to 20 */
  results?: number;
  /** 0 to 1: lowest meaning score a memory needs to be kept. */
  memory_floor?: number;
  /** 0 to 3: lowest judge mark a knowledge passage needs to be kept. */
  judge_min?: number;
  rerank?: boolean;
  rewrite?: boolean;
  memory_card?: boolean;
  mode?: "auto" | "agentic";
};

/** What live chat uses today, so the panel can say "Live chat uses 0.70". */
export type PlaygroundDefaults = Required<PlaygroundSettings>;

export type CompanionRequestKind = "chat" | "chat_continue" | "widget_session" | "widget_chat" | "widget_continue";
export type CompanionRequestRow = {
  id: number;
  companion_id: string | null;
  companion_name: string | null;
  kind: CompanionRequestKind;
  external_user_id: string | null;
  status: number;
  ms: number;
  created_at: string;
};
export type CompanionRequestLog = {
  requests: CompanionRequestRow[];
  daily: { date: string; ok: number; error: number }[];
  total: number;
  errors: number;
  median_ms: number | null;
  capped: boolean;
};

export type CompanionSearchIn = PlaygroundSources;
export type CompanionKnowledgeHit = {
  document: string;
  page_from: number;
  page_to: number;
  heading_path: string;
  text: string;
  /** 1 = the main resource, 2 = another book. */
  tier: number;
  step: "main" | "shortcut" | "books";
  /** The judge's mark 0 to 3. null = the judge was off. */
  score: number | null;
  /** Meaning match 0 to 1. null = not measured. */
  meaning: number | null;
  /** false = the judge (or the cut-off) dropped it. */
  kept: boolean;
};
export type CompanionMemoryHit = {
  kind: "messages" | "diary" | "fact";
  day: string | null;
  text: string;
  meaning: number | null;
  /** Word-match score, used when no person was given. */
  words: number | null;
  /** false = below the strictness floor. */
  kept: boolean;
  section?: string;
  /** Words mode (no person given) still says whose fact it is, and whether it is closed. */
  external_user_id?: string;
  display_name?: string | null;
  status?: "active" | "closed";
};
export type CompanionSearchResult = {
  in: CompanionSearchIn;
  /** false = small talk, nothing was searched. */
  needs_docs: boolean;
  /** true = the character has no collection to read. */
  no_collection: boolean;
  rewritten: { english: string; tamil: string; terms: string[]; needs_docs: boolean } | null;
  /** Kept first. */
  knowledge: CompanionKnowledgeHit[];
  /** Kept first, then below-floor. */
  memories: CompanionMemoryHit[];
  /** "words" = no person given: plain word match on facts across everyone. */
  memory_mode: "meaning" | "words" | null;
  memories_hidden: "private" | null;
  /** true = the knowledge side failed during an "all" search; memories still came back. */
  knowledge_error?: boolean;
};

const COMPANIONS = "/api/v1/companions";

export const companionsApi = {
  /** Active characters. archived=true → the Archived tab. */
  list: (archived = false) =>
    apiFetch<{ companions: Companion[] }>(archived ? `${COMPANIONS}?archived=true` : COMPANIONS).then((r) => r.companions),
  /** Hide it and stop it answering (status becomes paused). Chats and memory are kept. */
  archive: (id: string) => apiFetch<Companion>(`${COMPANIONS}/${id}/archive`, { method: "POST" }),
  /** Back to the list as Draft. */
  restore: (id: string) => apiFetch<Companion>(`${COMPANIONS}/${id}/restore`, { method: "POST" }),
  /** Delete permanently, with its chats and memory. Cannot be undone. */
  remove: (id: string) => apiFetch<void>(`${COMPANIONS}/${id}`, { method: "DELETE" }),
  get: (id: string) => apiFetch<Companion>(`${COMPANIONS}/${id}`),
  create: (data: CompanionInput & { name: string }) =>
    apiFetch<Companion>(COMPANIONS, { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, changes: CompanionInput) =>
    apiFetch<Companion>(`${COMPANIONS}/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),

  overview: () => apiFetch<CompanionOverview>(`${COMPANIONS}/overview`),

  memorySettings: () => apiFetch<{ memory_scope: CompanionMemoryScope }>(`${COMPANIONS}/memory-settings`),
  setMemorySettings: (memory_scope: CompanionMemoryScope) =>
    apiFetch<{ memory_scope: CompanionMemoryScope }>(`${COMPANIONS}/memory-settings`, {
      method: "PUT",
      body: JSON.stringify({ memory_scope }),
    }),

  keys: () => apiFetch<{ keys: CompanionApiKey[]; max_active: number }>(`${COMPANIONS}/keys`),
  createKey: () => apiFetch<CompanionApiKey & { key: string }>(`${COMPANIONS}/keys`, { method: "POST" }),
  revokeKey: (id: string) => apiFetchNoContent(`${COMPANIONS}/keys/${id}`, { method: "DELETE" }),

  install: (id: string) => apiFetch<CompanionInstall>(`${COMPANIONS}/${id}/install`),

  testChat: (
    id: string,
    message: string,
    opts: {
      tools?: CompanionAppTool[];
      model?: string;
      use_memory?: boolean;
      settings?: PlaygroundSettings;
      /** A test customer's external_user_id; left out = "You". */
      test_person?: string;
    } = {},
  ) =>
    apiFetch<CompanionReply>(`${COMPANIONS}/${id}/test-chat`, {
      method: "POST",
      body: JSON.stringify({ message, ...opts }),
    }),
  continueTestChat: (turn_id: string, results: { id: string; output: unknown }[]) =>
    apiFetch<CompanionReply>(`${COMPANIONS}/test-chat/continue`, {
      method: "POST",
      body: JSON.stringify({ turn_id, results }),
    }),

  personMemory: (id: string, externalUserId: string) =>
    apiFetch<{ facts: CompanionMemoryFact[]; memory_scope: CompanionMemoryScope }>(
      `${COMPANIONS}/${id}/people/${encodeURIComponent(externalUserId)}/memory`,
    ),
  personDiary: (id: string, externalUserId: string) =>
    apiFetch<CompanionDiary>(`${COMPANIONS}/${id}/people/${encodeURIComponent(externalUserId)}/diary`),
  deleteDiaryDay: (id: string, externalUserId: string, day: string) =>
    apiFetchNoContent(`${COMPANIONS}/${id}/people/${encodeURIComponent(externalUserId)}/diary/${day}`, {
      method: "DELETE",
    }),
  deleteRecap: (id: string, externalUserId: string) =>
    apiFetchNoContent(`${COMPANIONS}/${id}/people/${encodeURIComponent(externalUserId)}/recap`, { method: "DELETE" }),
  requests: (params: { kind?: CompanionRequestKind | ""; status?: "ok" | "error" | ""; days?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.kind) query.set("kind", params.kind);
    if (params.status) query.set("status", params.status);
    if (params.days) query.set("days", String(params.days));
    const qs = query.toString();
    return apiFetch<CompanionRequestLog>(`${COMPANIONS}/requests${qs ? `?${qs}` : ""}`);
  },

  models: () =>
    apiFetch<{ models: CompanionModel[]; default: string | null; playground_defaults?: PlaygroundDefaults }>(`${COMPANIONS}/models`),

  search: (
    id: string,
    body: { in: CompanionSearchIn; q: string; limit?: number; external_user_id?: string; settings?: PlaygroundSettings },
  ) =>
    apiFetch<CompanionSearchResult>(`${COMPANIONS}/${id}/search`, { method: "POST", body: JSON.stringify(body) }),

  people: (id: string, params: { q?: string; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.limit) query.set("limit", String(params.limit));
    if (params.offset) query.set("offset", String(params.offset));
    const qs = query.toString();
    return apiFetch<{ people: CompanionPerson[]; total: number; privacy_mode: "A" | "B" }>(
      `${COMPANIONS}/${id}/people${qs ? `?${qs}` : ""}`,
    );
  },
  /** The owner's test customers for the Playground ("You" first) and how many they may have. */
  testPeople: () => apiFetch<{ people: TestPerson[]; max: number }>(`${COMPANIONS}/test-people`),
  /** Add a test customer. 409 when the max is reached. */
  createTestPerson: (name: string) =>
    apiFetch<TestPerson>(`${COMPANIONS}/test-people`, { method: "POST", body: JSON.stringify({ name }) }),
  /** Wipe the test customer's chats and memories and remove it from the list. "You" cannot be deleted (400). */
  deleteTestPerson: (externalUserId: string) =>
    apiFetchNoContent(`${COMPANIONS}/test-people/${encodeURIComponent(externalUserId)}`, { method: "DELETE" }),
  /** Wipe the chats and memories but keep the name; the next chat is a first visit. Same id comes back. */
  startOverTestPerson: (externalUserId: string) =>
    apiFetch<TestPerson>(`${COMPANIONS}/test-people/${encodeURIComponent(externalUserId)}/start-over`, { method: "POST" }),
  /** Memory status of one test customer with one character. */
  testPersonMemory: (id: string, externalUserId: string) =>
    apiFetch<CompanionMemoryStatus>(`${COMPANIONS}/${id}/test-people/${encodeURIComponent(externalUserId)}/memory`),
  /** "Save now": run the memory save early. facts is null in privacy mode B. 409 for a Level 1 character, 502 if the AI call failed. */
  saveTestPersonMemory: (id: string, externalUserId: string) =>
    apiFetch<{ outcome: SaveMemoryOutcome; facts: number | null }>(
      `${COMPANIONS}/${id}/test-people/${encodeURIComponent(externalUserId)}/save-memory`,
      { method: "POST" },
    ),
  /** "Delete this person": chats and facts with every character. */
  forgetPerson: (externalUserId: string) =>
    apiFetchNoContent(`${COMPANIONS}/people/${encodeURIComponent(externalUserId)}`, { method: "DELETE" }),
  deleteFact: (id: string, externalUserId: string, factId: string) =>
    apiFetchNoContent(`${COMPANIONS}/${id}/people/${encodeURIComponent(externalUserId)}/memory/${factId}`, {
      method: "DELETE",
    }),
};

// ---------------------------------------------------------------------------
// Anril Agents knowledge base: collections of files, read page by page.
// Backend: routes/companion_kb.py. Example: a "Product guides"
// collection holds "Returns policy.pdf", 32 pages, read by Maya.
// ---------------------------------------------------------------------------

export type KbCollection = {
  id: string;
  name: string;
  book_count: number;
  page_count: number;
  pages_ok: number;
  read_by: { id: string; name: string }[];
  created_at: string;
  updated_at: string;
};
export type KbDocStatus = "processing" | "ready" | "ready_with_gaps" | "failed";
export type KbDocument = {
  id: string;
  collection_id: string;
  collection_name: string;
  title: string;
  file_type: string;
  size_bytes: number;
  tier: 1 | 2;
  page_count: number;
  status: KbDocStatus;
  source: "upload" | "sales_copy" | "owner_answers";
  error: string | null;
  pages_ok: number;
  pages_failed: number;
  pages_pending: number;
  failed_pages: number[];
  created_at: string;
  updated_at: string;
};
export type KbPage = {
  page_no: number;
  status: "pending" | "ok" | "failed";
  method: "text_layer" | "ocr" | null;
  attempts: number;
  char_count: number;
  error: string | null;
  updated_at: string;
  /** Only on getPage, not on listPages. */
  text?: string | null;
};
export type KbPassage = {
  id: string;
  seq: number;
  heading_path: string;
  text: string;
  page_from: number;
  page_to: number;
  tier: 1 | 2;
};
export type KbLimits = { max_bytes: number; accepted_types: string[] };
export type KbUploadTicket = { draft_id: string; upload_url: string; token: string; path: string; file_type: string };
export type KbSalesDocument = { id: string; name: string; file_type: string; created_at: string };
export type KbShortcut = {
  id: string;
  topic: string;
  document_id: string;
  document_title: string;
  pages: { page_from: number; page_to: number }[];
  uses: number;
  companion_id: string;
  companion_name: string;
  created_at: string;
};
export type KbGap = {
  id: string;
  topic: string;
  ask_count: number;
  last_asked_at: string;
  companion_id: string;
  companion_name: string;
};

const COMPANION_KB = "/api/v1/companion-kb";

/**
 * POST a JSON body to a route that answers with no result we read (204 or a small ack).
 * apiFetchNoContent drops the JSON content type, so a body-carrying POST needs this.
 * Same auth and same errors as apiFetch.
 */
async function kbPostJsonNoResult(path: string, body: unknown): Promise<void> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") window.location.href = "/login";
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    const error = new Error(errorDetailText(err.detail, "Request failed")) as ApiError;
    error.status = res.status;
    throw error;
  }
}

export const companionKbApi = {
  listCollections: () => apiFetch<KbCollection[]>(`${COMPANION_KB}/collections`),
  /** 409 = the name is taken. */
  createCollection: (name: string) =>
    apiFetch<KbCollection>(`${COMPANION_KB}/collections`, { method: "POST", body: JSON.stringify({ name }) }),
  renameCollection: (id: string, name: string) =>
    apiFetch<KbCollection>(`${COMPANION_KB}/collections/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  /** 409 = the collection still has books; the error text is meant for the owner. */
  deleteCollection: (id: string) => apiFetchNoContent(`${COMPANION_KB}/collections/${id}`, { method: "DELETE" }),

  limits: () => apiFetch<KbLimits>(`${COMPANION_KB}/limits`),

  listDocuments: (opts: { collectionId?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (opts.collectionId) query.set("collection_id", opts.collectionId);
    if (opts.limit) query.set("limit", String(opts.limit));
    const qs = query.toString();
    return apiFetch<KbDocument[]>(`${COMPANION_KB}/documents${qs ? `?${qs}` : ""}`);
  },
  getDocument: (id: string) => apiFetch<KbDocument>(`${COMPANION_KB}/documents/${id}`),
  /** Per-page status, no text. */
  listPages: (id: string) => apiFetch<KbPage[]>(`${COMPANION_KB}/documents/${id}/pages`),
  /** One page, with its text. */
  getPage: (id: string, pageNo: number) => apiFetch<KbPage>(`${COMPANION_KB}/documents/${id}/pages/${pageNo}`),
  listPassages: (id: string) => apiFetch<KbPassage[]>(`${COMPANION_KB}/documents/${id}/passages`),

  /** Step 1 of an upload: get a ticket, then uploadToTicket(), then registerDocument(). */
  createUpload: (name: string, sizeBytes: number) =>
    apiFetch<KbUploadTicket>(`${COMPANION_KB}/uploads`, {
      method: "POST",
      body: JSON.stringify({ name, size_bytes: sizeBytes }),
    }),
  registerDocument: (body: { draft_id: string; collection_id: string; tier: 1 | 2; title?: string }) =>
    apiFetch<KbDocument>(`${COMPANION_KB}/documents`, { method: "POST", body: JSON.stringify(body) }),
  updateDocument: (id: string, body: { tier?: 1 | 2; title?: string }) =>
    apiFetch<KbDocument>(`${COMPANION_KB}/documents/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteDocument: (id: string) => apiFetchNoContent(`${COMPANION_KB}/documents/${id}`, { method: "DELETE" }),
  retryDocument: (id: string) =>
    apiFetch<{ requeued: number }>(`${COMPANION_KB}/documents/${id}/retry`, { method: "POST" }),

  listSalesDocuments: () => apiFetch<KbSalesDocument[]>(`${COMPANION_KB}/sales-documents`),
  addFromSales: (body: { sales_document_id: string; collection_id: string; tier: 1 | 2 }) =>
    apiFetch<KbDocument>(`${COMPANION_KB}/documents/from-sales`, { method: "POST", body: JSON.stringify(body) }),

  listShortcuts: (collectionId: string) =>
    apiFetch<KbShortcut[]>(`${COMPANION_KB}/collections/${collectionId}/shortcuts`),
  deleteShortcut: (id: string) => apiFetchNoContent(`${COMPANION_KB}/shortcuts/${id}`, { method: "DELETE" }),

  listGaps: (collectionId: string) => apiFetch<KbGap[]>(`${COMPANION_KB}/collections/${collectionId}/gaps`),
  answerGap: (id: string, answer: string) => kbPostJsonNoResult(`${COMPANION_KB}/gaps/${id}/answer`, { answer }),
  dismissGap: (id: string) => apiFetchNoContent(`${COMPANION_KB}/gaps/${id}/dismiss`, { method: "POST" }),

  /**
   * Sends the file straight to storage (a signed upload URL), not through the
   * backend. The URL carries the permission, so no Authorization header.
   * XMLHttpRequest, not fetch, so progress can be reported.
   * Aborting `signal` stops the upload and rejects with UploadCancelledError.
   */
  uploadToTicket: (ticket: KbUploadTicket, file: File, onProgress?: (fraction: number) => void, signal?: AbortSignal) =>
    new Promise<void>((resolve, reject) => {
      if (signal?.aborted) {
        reject(new UploadCancelledError());
        return;
      }
      const xhr = new XMLHttpRequest();
      signal?.addEventListener("abort", () => xhr.abort(), { once: true });
      xhr.open("PUT", ticket.upload_url);
      xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
      xhr.upload.onprogress = (e) => {
        if (onProgress && e.lengthComputable && e.total > 0) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          onProgress?.(1);
          resolve();
        } else {
          reject(new Error(`Upload failed (${xhr.status}). Please try again.`));
        }
      };
      xhr.onerror = () => reject(new Error("Upload failed. Check your connection and try again."));
      xhr.ontimeout = () => reject(new Error("Upload timed out. Please try again."));
      xhr.onabort = () => reject(new UploadCancelledError());
      xhr.send(file);
    }),
};

/** The person pressed Cancel while a knowledge file was uploading. Not a failure: nothing was saved. */
export class UploadCancelledError extends Error {
  constructor() {
    super("Upload cancelled.");
    this.name = "UploadCancelledError";
  }
}

/** For 204 responses (no JSON body). Same errors as apiFetch. */
async function apiFetchNoContent(path: string, opts: RequestInit): Promise<void> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, { ...opts, headers: { ...authHeaders } });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") window.location.href = "/login";
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    const error = new Error(errorDetailText(err.detail, "Request failed")) as ApiError;
    error.status = res.status;
    throw error;
  }
}
