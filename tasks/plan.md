# Implementation Plan: Sand glass login page

## Overview
Replace the navy-gradient login at `frontend/app/(auth)/login/page.tsx` with the approved mockup (canvas v15, board `Sand.dc.html`).

**Layout:**
- **Background:** warm sand #F1EFE8.
- **Left: one teal glass panel** containing:
  - the headline and paragraph option 1
  - three chips
  - the flowing message bubbles
  - the line "A product from Bloom Matrix"
- **Corner characters:** Healy (video) perched on the panel's top-right corner, Tealy (video) on its bottom-left corner.
- **Right: a white form card** with:
  - email and password
  - Sign in
  - Continue with Google
  - Use a passkey instead
  - a Reset password flow

## Architecture Decisions
- **Split the page in two.**
  - `components/auth/LoginShowcase.tsx` (plus a CSS module) holds everything decorative.
  - `page.tsx` keeps all auth logic and passes two flags down: `peek` (password field focused) and `flying` (sign-in running).
  - The showcase has no auth code, so it can't break sign-in.
- **CSS module for the motion, Tailwind for the form.** This matches `components/site/HomeHero.module.css`. Sand, copper and glass colours live as local CSS variables in the module. The shared teal comes from the existing `--primary-*` tokens.
- **Videos are desktop-only.**
  - `<video>` only renders at widths of 1024px and up, so phones never download about 2.3 MB.
  - Phones and reduced-motion users get still poster images instead.
- **Fix for white boxes around the videos.** `mix-blend-mode: multiply` goes on each character's outermost wrapper, not on the `<video>`. A transformed parent isolates blending and would show a white box.
- **Reset password reuses the existing `/auth/callback`.**
  - The callback gains a `next` parameter that is checked against an allow-list (`/dashboard`, `/reset-password`).
  - Nothing else is accepted, which blocks open-redirects.
  - `next` lives in a tiny pure helper with a vitest test.
- **No new no-workspace guard is needed.**
  - `AuthRoleContext.tsx:123` already catches the 403 "No tenant associated", signs the user out and sends them to `/login?reason=removed`.
  - We only reword that message so it also fits a first-time Google user.
- **The auth work is done by the planner itself, not delegated.** That covers the Google button, the callback and reset password. They get a `security-reviewer` pass before commit.

## Worked examples
- **Google sign-in, existing user.** Priya's owner account is priya@… with a password.
  1. She clicks Continue with Google and Supabase sends her to Google.
  2. Google returns to `/auth/callback?code=…`. The code is exchanged and she lands on `/dashboard`.
  3. Supabase links the Google identity to her existing user because the email matches.
- **Google sign-in, unknown email.** Someone signs in with random@gmail.com.
  1. Supabase creates an auth user with no workspace.
  2. The dashboard calls `/team/me` and gets 403.
  3. The existing guard signs them out and they see: "This account isn't part of an anril workspace. Ask your admin to invite you."
- **Forgotten password.** A telecaller clicks Reset password.
  1. The card swaps to "Email me a reset link", they enter their email and press Send.
  2. They always see the same message: "If that email has an account, a link is on its way." It never reveals whether the account exists.
  3. The email link goes to `/auth/callback?code=…&next=/reset-password`, which opens `/reset-password`.
  4. They enter a new password twice (8+ characters, same rule as `ChangePasswordCard`), then `updateUser`, then `/dashboard`.
  5. If the link has expired, they see "This link has expired, request a new one" with a button back to login.

## Task List

### Phase 1: Showcase
- [ ] Task 1: Ship the video and still assets, and keep middleware off them
- [ ] Task 2: Build LoginShowcase (glass panel, bubbles, corner characters) and mount it

### Checkpoint 1
- [ ] typecheck and lint clean
- [ ] Screenshot at 1280×800 matches the mockup: no white boxes, both videos play, blur visible

### Phase 2: Form and auth
- [ ] Task 3: Restyle the form card and wire the peek and fly interactions; mobile layout
- [ ] Task 4: Continue with Google button only, behind the `NEXT_PUBLIC_GOOGLE_SIGNIN` flag (off: shows "coming soon"); real sign-in deferred until the Supabase setup
- [ ] Task 5: Reset password: request link, safe `next` in callback, `/reset-password` page

### Checkpoint 2
- [ ] vitest passes (new `safeNext` test included)
- [ ] `security-reviewer` pass on the Task 5 diff, with the security-checklist
- [ ] Local end-to-end run (`make dev-backend` plus frontend):
  - password login works
  - passkey login works
  - reset email arrives and the new password works
  - Google works once the provider is set up
- [ ] UI QA pass as the UI test tenant

### Phase 3: Cleanup (needs your OK)
- [ ] Task 6: Delete the orphaned `BackgroundAnimation.tsx`; rename Zephyr to Tealy in connect-channels

### Checkpoint: Complete
- [ ] `/review` on the full diff
- [ ] Commit to main only when you say so; no push

## Your setup steps (secrets: I can't do these)
Step 3 is needed now, for reset password. Steps 1–2 can wait until you switch Google on: set `NEXT_PUBLIC_GOOGLE_SIGNIN=true` after doing them.

1. **Google Cloud Console:** create an OAuth client of type "Web application". Set the authorised redirect URI to `https://<your-project>.supabase.co/auth/v1/callback`.
2. **Supabase:** go to Authentication → Providers → Google, turn it on and paste the client ID and secret.
3. **Supabase:** go to Authentication → URL Configuration and add both of these to the Redirect URLs list:
   - `https://<prod-domain>/auth/callback`
   - `http://localhost:3000/auth/callback`

   Without this, reset links fall back to the Site URL.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| White box around videos (blend isolated by a transformed parent) | High (looks broken) | Blend on the outermost wrapper; check screenshots in Chrome and Safari |
| Safari can't play VP9 WebM | Med | `<source>` order: WebM first, MP4 fallback |
| Autoplay blocked (React doesn't render the `muted` attribute) | Med | Set `muted` on a ref before calling `play()`; poster shows if it is still blocked |
| Open redirect through `?next=` | High (security) | Exact allow-list in `safeNext()`, with a unit test covering `//evil.com`, `https://…` and `/\evil` |
| Reset form reveals which emails have accounts | Med (security) | Same message whatever Supabase returns |
| Unknown Google emails create empty auth users | Low | Existing 403 guard signs them out; optionally turn off public sign-ups (open question) |
| Video weight (~2.3 MB) slows login | Med | Desktop-only `<video>`, posters, files served as static assets |
| `backdrop-filter` is slow on weak laptops | Low | One panel only; plain translucent teal if unsupported |
| Teammate edits on the same files | Low | No commits on these files since 2026-10-08; `git fetch` before building |

## Open Questions
1. What is the production domain, for the Supabase redirect allow-list?
2. *(Deferred with Google)* Turn off "Allow new users to sign up" in Supabase?
3. Task 6 (delete `BackgroundAnimation.tsx`, rename Zephyr to Tealy): now, or a separate change?
4. Phones (under 1024px): show the form plus a compact glass header (headline and Bloom Matrix line), with no bubbles or characters. OK?
