"use client";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { companionsApi, type TestPerson } from "@/lib/api";
import { BTN_SECONDARY, INPUT } from "@/components/agents/ui";

export const APP_DATA_MAX = 12000;   // = backend models.MAX_APP_DATA_CHARS
export const PROFILE_NAME_MAX = 100;   // = companion_end_users.profile_name check (migration 290)

/** Fired after a save so the person chips show the new profile name. detail: { external_user_id, profile_name }. */
export const PROFILE_SAVED_EVENT = "aira:test-person-profile";

type Status = "loading" | "idle" | "saving" | "saved" | "error";

/**
 * "This person's app data": what the business's app would send about this test person with every
 * message, saved per test person. Example: Meena's chart (லக்னம்: மீனம், 7ம் இடம் கன்னி: சனி ...) is
 * saved once; every Playground message as Meena then carries it, the way AstroTamil's server sends
 * app_data on /chat. Switching to Ravi loads Ravi's own (or an empty box).
 * "Whose profile is this?" says whose the data is: Vivek testing Karthik's chart types "Karthik", and the
 * reply then calls the user Vivek and the chart Karthik's (the WHO line, like profile_name on /chat).
 */
export function AppDataBox({ person }: { person: TestPerson | undefined }) {
  const id = person?.external_user_id;
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  const [profile, setProfile] = useState("");
  const [savedProfile, setSavedProfile] = useState("");
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    let live = true;
    setStatus("loading");
    setError("");
    companionsApi
      .testPersonAppData(id)
      .then((r) => {
        if (!live) return;
        setText(r.app_data ?? "");
        setSaved(r.app_data ?? "");
        setProfile(r.profile_name ?? "");
        setSavedProfile(r.profile_name ?? "");
        setStatus("idle");
      })
      .catch((e: Error) => {
        if (!live) return;
        setError(e.message || "Could not load this person's app data.");
        setStatus("error");
      });
    return () => {
      live = false;   // a slow answer for the previous person is dropped
    };
  }, [id]);

  const save = async () => {
    if (!id) return;
    setStatus("saving");
    setError("");
    try {
      const r = await companionsApi.saveTestPersonAppData(id, text.trim(), profile.trim());
      setText(r.app_data ?? "");
      setSaved(r.app_data ?? "");
      setProfile(r.profile_name ?? "");
      setSavedProfile(r.profile_name ?? "");
      setStatus("saved");
      window.dispatchEvent(
        new CustomEvent(PROFILE_SAVED_EVENT, { detail: { external_user_id: id, profile_name: r.profile_name ?? null } }),
      );
    } catch (e) {
      setError((e as Error).message || "Could not save. Try again.");
      setStatus("error");
    }
  };

  const name = person?.is_you ? "You" : person?.name || "this person";
  const tooLong = text.length > APP_DATA_MAX;
  const changed = text.trim() !== saved.trim() || profile.trim() !== savedProfile.trim();
  const empty = !text.trim() && !profile.trim();
  const busy = status === "loading" || status === "saving";
  return (
    <div>
      <label htmlFor="pg-app-data" className="text-sm font-semibold text-ink">
        {name}&apos;s app data
      </label>
      <p id="pg-app-data-hint" className="mb-2.5 mt-0.5 text-xs text-ink-muted">
        What your app knows about this person: profile, account or chart. Sent with every message, the way your
        app&apos;s server sends <code className="font-mono">app_data</code>. Saved for this test person only.
      </p>
      <textarea
        id="pg-app-data"
        aria-describedby="pg-app-data-hint pg-app-data-count"
        rows={7}
        value={text}
        disabled={!id || status === "loading"}
        onChange={(e) => {
          setText(e.target.value);
          if (status === "saved") setStatus("idle");
        }}
        placeholder={"லக்னம்: மீனம்\n7ம் இடம் கன்னி: சனி\nதசை: ராகு, புத்தி: குரு (2025-02 → 2027-07)"}
        className={cn(INPUT, "min-h-[140px] font-mono text-xs leading-relaxed")}
      />
      <label htmlFor="pg-profile-name" className="mt-3 block text-xs font-semibold text-ink">
        Whose profile is this? <span className="font-normal text-ink-muted">(optional)</span>
      </label>
      <p id="pg-profile-name-hint" className="mb-1.5 mt-0.5 text-xs text-ink-muted">
        When {name} asks about someone else&apos;s chart or account. The reply calls {name} by name and the profile by this
        one, the way your app sends <code className="font-mono">profile_name</code>.
      </p>
      <input
        id="pg-profile-name"
        aria-describedby="pg-profile-name-hint"
        value={profile}
        maxLength={PROFILE_NAME_MAX}
        disabled={!id || status === "loading"}
        onChange={(e) => {
          setProfile(e.target.value);
          if (status === "saved") setStatus("idle");
        }}
        placeholder="e.g. Karthik"
        className={cn(INPUT, "text-sm")}
      />
      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
        <span id="pg-app-data-count" className={cn("text-xs", tooLong ? "text-danger" : "text-ink-muted")}>
          {text.length.toLocaleString()} / {APP_DATA_MAX.toLocaleString()} characters · plain lines or JSON
        </span>
        <span className="flex items-center gap-2">
          {status === "saved" && !changed && <span className="text-xs text-ink-muted" role="status">Saved</span>}
          <button type="button" onClick={save} disabled={!id || busy || tooLong || !changed} className={cn(BTN_SECONDARY, "min-h-8")}>
            {status === "saving" ? "Saving…" : !empty || !(saved || savedProfile) ? "Save" : "Clear"}
          </button>
        </span>
      </div>
      {error && (
        <p role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
