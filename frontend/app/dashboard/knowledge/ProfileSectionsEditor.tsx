"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Save, History, Loader2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { API_URL, getAuthHeaders } from "@/lib/api";
import {
  ProfileSection,
  ProfileResponse,
  SECTION_KEYS_ORDERED,
  SECTION_HELP_FALLBACK,
  wordCount,
  totalWords,
  sectionState,
} from "./profileSections";
import ConvertToSectionsModal, { type ConvertResult } from "./ConvertToSectionsModal";
import { AutoGrowTextarea } from "./useAutoGrow";

interface ProfileSectionsEditorProps {
  canEdit: boolean;
  onOpenHistory: () => void;
  onSaved?: (renderedWordCount: number) => void;
}

export default function ProfileSectionsEditor({
  canEdit,
  onOpenHistory,
  onSaved,
}: ProfileSectionsEditorProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showConvertModal, setShowConvertModal] = useState(false);

  const [sections, setSections] = useState<Record<string, ProfileSection>>({});
  const [sectionTexts, setSectionTexts] = useState<Record<string, string>>({});
  const [other, setOther] = useState("");
  const [initialOther, setInitialOther] = useState("");
  const [total, setTotal] = useState(0);
  const [hardLimit, setHardLimit] = useState(700);
  const [isStructured, setIsStructured] = useState(false);

  async function loadProfile() {
    setLoading(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/ai-tune/profile`, { headers: auth });

      if (res.status === 403) {
        // Non-owner; read-only
        return;
      }

      if (!res.ok) {
        throw new Error("Failed to load profile");
      }

      const data: ProfileResponse = await res.json();
      const secMap: Record<string, ProfileSection> = {};
      const textMap: Record<string, string> = {};

      for (const section of data.sections) {
        secMap[section.key] = section;
        textMap[section.key] = section.text;
      }

      setSections(secMap);
      setSectionTexts(textMap);
      setOther(data.other);
      setInitialOther(data.other);
      setTotal(data.total_words);
      setHardLimit(data.hard_limit);
      setIsStructured(data.is_structured);
    } catch {
      toast.error("Failed to load profile. Please refresh the page.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProfile();
  }, []);

  async function handleSave() {
    setSaving(true);
    try {
      const auth = await getAuthHeaders();
      const payload = {
        sections: sectionTexts,
        other,
      };

      const res = await fetch(`${API_URL}/api/v1/ai-tune/profile`, {
        method: "PUT",
        headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.status === 422) {
        const error = await res.json();
        toast.error(error.detail || "Too many words.");
        return;
      }

      if (!res.ok) {
        throw new Error("Failed to save");
      }

      const updated: ProfileResponse = await res.json();
      const secMap: Record<string, ProfileSection> = {};
      const textMap: Record<string, string> = {};

      for (const section of updated.sections) {
        secMap[section.key] = section;
        textMap[section.key] = section.text;
      }

      setSections(secMap);
      setSectionTexts(textMap);
      setOther(updated.other);
      setInitialOther(updated.other);
      setTotal(updated.total_words);
      setIsStructured(updated.is_structured);

      toast.success("Saved.");
      if (onSaved) {
        onSaved(updated.total_words);
      }
    } catch {
      toast.error("Failed to save. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  const currentTotal = totalWords(sectionTexts, other);
  const isDirty =
    currentTotal !== total ||
    other !== initialOther ||
    Object.entries(sectionTexts).some(([k, v]) => sections[k]?.text !== v);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[200px]">
        <Loader2 size={20} className="animate-spin text-primary" />
      </div>
    );
  }

  if (!canEdit) {
    return (
      <div className="bg-surface rounded-2xl p-6 md:p-8 border border-surface-mid shadow-sm">
        <div className="flex items-start gap-2">
          <AlertTriangle size={16} className="text-amber-600 flex-shrink-0 mt-0.5" />
          <p className="font-body text-sm text-on-surface">
            Only the account owner can edit the business profile.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header & Word Counter */}
      <div className="bg-surface rounded-2xl p-6 md:p-8 border border-surface-mid shadow-sm space-y-4">
        <div>
          <h2 className="font-display text-lg font-bold text-primary">Business Profile</h2>
          <p className="font-body text-xs text-on-surface-muted mt-1 leading-relaxed">
            Keep it under 700 words — the profile below has a word budget per section. This
            structured approach helps Anril respond more accurately and consistently.
          </p>
        </div>

        {/* Word Count Bar */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs font-semibold text-on-surface">
              {currentTotal.toLocaleString()} / {hardLimit} words
            </span>
            {currentTotal > hardLimit && (
              <span className="font-mono text-xs font-semibold text-red-700">
                {currentTotal - hardLimit} over limit
              </span>
            )}
          </div>
          <div className="w-full h-2 bg-surface-low rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full transition-colors duration-200",
                currentTotal <= 520
                  ? "bg-emerald-500"
                  : currentTotal <= hardLimit
                    ? "bg-amber-500"
                    : "bg-red-500"
              )}
              style={{
                width: `${Math.min((currentTotal / hardLimit) * 100, 100)}%`,
              }}
            />
          </div>
        </div>
      </div>

      {/* "Not in a section yet" block */}
      {other && (
        <div className="bg-surface rounded-2xl p-6 md:p-8 border border-surface-mid shadow-sm space-y-4">
          <div>
            <label htmlFor="other-textarea" className="font-display text-sm font-bold text-primary">
              Not in a section yet
            </label>
            <p className="font-body text-xs text-on-surface-muted mt-1 leading-relaxed">
              Text from your original description that hasn&apos;t been organized into sections yet. Use
              the &quot;Convert to sections&quot; button below to let Anril sort it automatically.
            </p>
          </div>

          <textarea
            id="other-textarea"
            value={other}
            onChange={(e) => setOther(e.target.value)}
            rows={4}
            className="w-full px-4 py-3.5 rounded-xl bg-surface-low border border-surface-mid font-body text-sm leading-relaxed text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-colors"
          />

          <div className="flex items-center justify-between pt-2">
            <span className="font-mono text-xs text-on-surface-muted">
              {wordCount(other)} words
            </span>
          </div>

          <button
            onClick={() => setShowConvertModal(true)}
            className="w-full px-4 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 transition-colors shadow-sm"
          >
            Convert to sections
          </button>
        </div>
      )}

      {/* Sections */}
      <div className="space-y-4">
        {SECTION_KEYS_ORDERED.map((key) => {
          const section = sections[key];
          if (!section) return null;

          const text = sectionTexts[key] || "";
          const words = wordCount(text);
          const state = sectionState(words, section.word_limit);

          return (
            <div key={key} className="bg-surface rounded-2xl p-6 md:p-8 border border-surface-mid shadow-sm space-y-3">
              <div>
                <label htmlFor={`section-${key}`} className="font-display text-sm font-bold text-primary">
                  {section.label}
                </label>
                {(section.hint || SECTION_HELP_FALLBACK[key]) && (
                  <p className="font-body text-xs text-on-surface-muted mt-1 leading-relaxed">
                    {section.hint || SECTION_HELP_FALLBACK[key]}
                  </p>
                )}
              </div>

              <AutoGrowTextarea
                id={`section-${key}`}
                value={text}
                onChange={(e) =>
                  setSectionTexts((prev) => ({ ...prev, [key]: e.target.value }))
                }
                minRows={3}
                className="w-full px-4 py-3.5 rounded-xl bg-surface-low border border-surface-mid font-body text-sm leading-relaxed text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-colors"
              />

              <div className="flex items-center justify-between pt-1">
                <span
                  className={cn(
                    "font-mono text-xs",
                    state === "over" ? "font-semibold text-amber-700" : "text-on-surface-muted"
                  )}
                >
                  {words} / {section.word_limit} words
                  {state === "over" && " — over the suggested length"}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Convert to sections button (when structured is false) */}
      {!isStructured && !other && (
        <button
          onClick={() => setShowConvertModal(true)}
          className="w-full px-4 py-2.5 bg-surface border border-surface-mid text-on-surface rounded-xl font-label text-sm font-semibold hover:bg-surface-low transition-colors shadow-sm"
        >
          Convert to sections
        </button>
      )}

      {/* Action Buttons */}
      <div className="flex items-center justify-between pt-2">
        <button
          onClick={onOpenHistory}
          className="flex items-center gap-2 px-4 py-2.5 bg-surface border border-surface-mid text-on-surface rounded-xl font-label text-sm font-semibold hover:bg-surface-low transition-colors shadow-sm"
        >
          <History size={14} /> History
        </button>

        <button
          onClick={handleSave}
          disabled={saving || !isDirty || currentTotal > hardLimit}
          className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
        >
          <Save size={14} /> {saving ? "Saving…" : "Save"}
        </button>
      </div>

      {/* Convert Modal */}
      {showConvertModal && (
        <ConvertToSectionsModal
          text={other}
          onClose={() => setShowConvertModal(false)}
          onApply={(converted: ConvertResult) => {
            const secMap: Record<string, ProfileSection> = {};
            const textMap: Record<string, string> = {};

            for (const section of Object.values(sections)) {
              secMap[section.key] = section;
              textMap[section.key] = converted.sections[section.key] || "";
            }

            setSections(secMap);
            setSectionTexts(textMap);
            setOther("");
            setShowConvertModal(false);
          }}
        />
      )}
    </div>
  );
}
