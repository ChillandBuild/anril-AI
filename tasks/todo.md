# Sand glass login: tasks

Plan: tasks/plan.md

## Task 1: Assets and middleware (XS)
**Description:** Copy the approved loops and stills into the app, and stop middleware from running a Supabase check on every video request.

**Acceptance criteria:**
- [x] These files exist in `frontend/public/login/`:
  - `tealy.webm` and `tealy.mp4`
  - `healy.webm` and `healy.mp4`
  - `tealy-poster.png` and `healy-poster.png` (first frames)
  - `healy-shut.png`
- [x] The middleware matcher skips `mp4` and `webm`, as it already does for images.

**Verification:**
- [x] `npm run typecheck`
- [x] With the dev server running, `curl -I localhost:3000/login/tealy.webm` returns 200 with `video/webm`.

**Dependencies:** None
**Files:** `frontend/public/login/*`, `frontend/middleware.ts`

## Task 2: LoginShowcase (M)
**Description:** Port the mockup's left side into `components/auth/LoginShowcase.tsx` plus `LoginShowcase.module.css`, and mount it in `page.tsx` in place of the old left half. The form logic stays as it is.

**What it contains:**
- Glass panel with the headline "Every lead, answered in seconds."
- Paragraph option 1: From "Fees evvalavu?" to a booked visit. anril AI handles the chat, you close the deal.
- Chips, and the line "A product from Bloom Matrix".
- Four bubbles rising, with typing → done and the HOT LEAD badge.
- Ping rings.
- Teal and copper glows.
- Healy on the top-right corner and Tealy on the bottom-left: videos, multiply blend, mouse lean.
- Healy's eyes shut when `peek` is true; Tealy flies off when `flying` is true.

**Acceptance criteria:**
- [x] At 1280×800 it matches mockup v15: no white boxes, both videos loop, blur visible.
- [x] `prefers-reduced-motion` shows posters with nothing moving.
- [x] Under 1024px, no `<video>` is in the DOM.

**Verification:**
- [x] `npm run typecheck`
- [x] `npm run lint`
- [ ] Look at local screenshots in Chrome and Safari.

**Dependencies:** Task 1
**Files:** `frontend/components/auth/LoginShowcase.tsx`, `frontend/components/auth/LoginShowcase.module.css`, `frontend/app/(auth)/login/page.tsx`

## Checkpoint 1
- [x] typecheck and lint clean
- [ ] Screenshot reviewed with Prem

## Task 3: Form card and interactions (S)
**Description:** Restyle the right side to match the mockup: sand page, white card, warm-grey inputs, solid teal Sign in, Google button slot, passkey link. Wire the interactions and the phone layout.

**Interactions:**
- Password focus sets `peek`.
- Submit sets `flying`. An error clears it, so Tealy comes back.

**Phone layout:** the form plus a compact glass header.

**Acceptance criteria:**
- [ ] Password login and passkey login behave exactly as before.
- [x] The `BackgroundAnimation` import and the old icons are gone.
- [x] Every field has a label, focus rings are visible, and the error text is announced (`role="alert"`).

**Verification:**
- [x] typecheck and lint
- [ ] Manual check: sign in with the UI test tenant locally.

**Dependencies:** Task 2
**Files:** `frontend/app/(auth)/login/page.tsx`

## Task 4: Continue with Google button, switched off for now (XS)
**Description:** Show the button now. The real Google sign-in waits until Prem does the Supabase setup.

**How it behaves:**
- The flag `NEXT_PUBLIC_GOOGLE_SIGNIN` is unset by default.
  - While it's off, a click shows a note: "Google sign-in is coming soon. Use your email and password for now."
  - It does not call Supabase. With the provider off, that call would land the user on a raw JSON error page.
- Later: set the flag to `true`. The button then calls `signInWithOAuth({ provider: "google", options: { redirectTo: origin + "/auth/callback" } })`, with no code change.

**Acceptance criteria:**
- [x] The button is visible and styled as in the mockup.
- [x] With the flag off, a click shows the note and makes no network call.

**Verification:**
- [x] typecheck and lint
- [x] Manual check: click it, see the note, and the Network tab shows no request.

**Dependencies:** Task 3
**Files:** `frontend/app/(auth)/login/page.tsx`

**Deferred until Prem sets up Google:**
- Turn the flag on.
- Test an existing user and an unknown email.
- Reword the `reason=removed` message to fit first-time Google users.

## Task 5: Reset password (M, auth: planner only)
**Description:** Add the full forgotten-password flow, from the link request to setting the new password.

**What changes:**
- If the callback's code exchange fails (expired or reused link), it redirects to `/login?reason=link`.
- The "Reset password" link swaps the card to an "Email me a reset link" view, which calls `resetPasswordForEmail(email, { redirectTo: origin + "/auth/callback?next=/reset-password" })`.
- It always shows the same message, so it never reveals which emails have accounts.
- New `lib/auth-redirect.ts` exports `safeNext()`, which accepts only `/dashboard` and `/reset-password`. The callback uses it.
- New `app/(auth)/reset-password/page.tsx`:
  - checks for a session, and shows an expired-link state if there isn't one
  - asks for the new password twice, 8+ characters
  - calls `updateUser`, then goes to `/dashboard`

**Acceptance criteria:**
- [ ] Full loop works locally: request, email, new password, signed in.
- [x] `safeNext` rejects `//evil.com`, `https://evil.com`, `/\evil` and unknown paths.
- [x] An expired or reused link shows the expired state, not a crash.

**Verification:**
- [x] `cd frontend && npx vitest run lib/auth-redirect.test.ts`
- [x] typecheck and lint
- [ ] Manual run of the full loop.

**Dependencies:** Task 3; Prem's setup step 3
**Files:** `frontend/app/(auth)/login/page.tsx`, `frontend/app/auth/callback/route.ts`, `frontend/lib/auth-redirect.ts`, `frontend/lib/auth-redirect.test.ts`, `frontend/app/(auth)/reset-password/page.tsx`

## Checkpoint 2
- [x] `npm test` (vitest) passes, apart from the known LeadsClient.tsx:472 brand-colour failure
- [x] `security-reviewer` pass on the Task 5 diff
- [ ] UI QA as the UI test tenant (local: `make dev-backend` + `NEXT_PUBLIC_API_URL=http://localhost:8000`)

## Task 6: Cleanup (S, needs OK)
**Description:** Remove the leftover old login animation and finish the Zephyr → Tealy rename.

**Acceptance criteria:**
- [ ] `components/BackgroundAnimation.tsx` is deleted, after confirming no other file imports it.
- [ ] In connect-channels, `ZephyrCourier` becomes `TealyCourier`, the alt text says Tealy, and the image files are renamed.
- [ ] The voice option "Zephyr (Bright)" in `config.tsx` is left alone.

**Verification:**
- [ ] typecheck, lint, vitest
- [ ] grep shows no `Zephyr` left except the voice option.

**Dependencies:** Checkpoint 2
**Files:** `frontend/components/BackgroundAnimation.tsx`, `frontend/app/dashboard/settings/connect-channels/{ui,EmbeddedSection,ManualSection}.tsx`, `frontend/public/illustrations/*`

## Checkpoint: Complete
- [ ] `/review` on the full diff
- [ ] Commit only on Prem's go; no push
