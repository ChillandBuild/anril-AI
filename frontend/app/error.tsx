"use client";
import { errorCode } from "@/components/first-setup/helpers";

// The last safety net for any page without its own error screen. No stack trace, only a short code
// the owner can read out to the Anril team.
export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const code = errorCode(error.digest);
  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center bg-[#F1EFE8] px-6 text-center">
      <h1 className="text-2xl font-extrabold tracking-tight text-[#0A1528]">Something went wrong. Nothing you saved is lost.</h1>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-[#556274]">
        Please try again. If it keeps happening, tell the Anril team
        {code ? " and give them this code." : "."}
      </p>
      {code && <p className="mt-3 rounded-lg bg-white px-3 py-1.5 font-mono text-sm text-[#0A1528]">Code: {code}</p>}
      <button
        type="button"
        onClick={reset}
        className="mt-6 rounded-2xl bg-[#0A1528] px-6 py-3 text-sm font-bold text-white"
      >
        Try again
      </button>
    </div>
  );
}
