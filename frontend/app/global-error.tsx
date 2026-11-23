"use client";
import { errorCode } from "@/components/first-setup/helpers";

// Replaces the whole page when even the root layout fails, so it brings its own <html> and plain styles.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const code = errorCode(error.digest);
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100dvh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          textAlign: "center",
          background: "#F1EFE8",
          color: "#0A1528",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 800, margin: 0 }}>Something went wrong. Nothing you saved is lost.</h1>
        <p style={{ maxWidth: 420, fontSize: 14, lineHeight: 1.5, color: "#556274" }}>
          Please try again. If it keeps happening, tell the Anril team{code ? " and give them this code." : "."}
        </p>
        {code && (
          <p style={{ background: "#fff", padding: "6px 12px", borderRadius: 8, fontFamily: "monospace", fontSize: 14 }}>
            Code: {code}
          </p>
        )}
        <button
          type="button"
          onClick={reset}
          style={{ marginTop: 20, padding: "12px 24px", borderRadius: 16, border: 0, background: "#0A1528", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer" }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
