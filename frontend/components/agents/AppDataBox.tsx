"use client";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { companionsApi, type TestPerson } from "@/lib/api";
import { BTN_SECONDARY, INPUT } from "@/components/agents/ui";

export const APP_DATA_MAX = 4000;   // = backend models.MAX_APP_DATA_CHARS

type Status = "loading" | "idle" | "saving" | "saved" | "error";

/**
 * "This person's app data": what the business's app would send about this test person with every
 * message, saved per test person. Example: Meena's chart (லக்னம்: மீனம், 7ம் இடம் கன்னி: சனி ...) is
 * saved once; every Playground message as Meena then carries it, the way AstroTamil's server sends
 * app_data on /chat. Switching to Ravi loads Ravi's own (or an empty box).
 */
export function AppDataBox({ person }: { person: TestPerson | undefined }) {
  const id = person?.external_user_id;
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
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
      const r = await companionsApi.saveTestPersonAppData(id, text.trim());
      setText(r.app_data ?? "");
      setSaved(r.app_data ?? "");
      setStatus("saved");
    } catch (e) {
      setError((e as Error).message || "Could not save. Try again.");
      setStatus("error");
    }
  };

  const name = person?.is_you ? "You" : person?.name || "this person";
  const tooLong = text.length > APP_DATA_MAX;
  const changed = text.trim() !== saved.trim();
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
      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
        <span id="pg-app-data-count" className={cn("text-xs", tooLong ? "text-danger" : "text-ink-muted")}>
          {text.length.toLocaleString()} / {APP_DATA_MAX.toLocaleString()} characters · plain lines or JSON
        </span>
        <span className="flex items-center gap-2">
          {status === "saved" && !changed && <span className="text-xs text-ink-muted" role="status">Saved</span>}
          <button type="button" onClick={save} disabled={!id || busy || tooLong || !changed} className={cn(BTN_SECONDARY, "min-h-8")}>
            {status === "saving" ? "Saving…" : text.trim() || !saved ? "Save" : "Clear"}
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
