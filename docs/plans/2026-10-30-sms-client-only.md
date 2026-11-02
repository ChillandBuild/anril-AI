# SMS client-only cleanup — approved scope

Approved by Prem in chat on 30 October 2026: “change it now”. This supersedes the reseller/payment/pricing scope of 2026-10-30-bulk9-sms-full-build.md. Work only in existing sms-bulk9 worktree. Do not apply migrations, merge, push, deploy, send paid messages or change provider accounts.

## Product contract

Bulk9 owns reseller administration and all financial work/information: accounts, plans, rates, credit allocations, recharges, payments, charges, stock and profit. Clients pay Prem offline.

Anril keeps five client tabs: Campaigns, Templates (including all DLT forms/uploads and template requests), Reports, Balance (remaining SMS credits only; Contact Anril to recharge), OTP & Developer (including owner-only key access). Preserve campaign scheduling, SMS segment estimates, delivery/failure reports and CSV export, but no rupee values, prices, costs, wallet money or financial exports.

Operator Console → Client → Configuration contains minimal Bulk9 key connection, masked status and webhook setup/retry; preserve existing sms feature controls. Remove standalone operator SMS view and stock cards. Keep a small template-request management surface in Configuration so retained client requests have an operator destination.

## Implementation slices and ownership

1. Backend client services/routes/tests: remove money computation/storage/API output, ledger endpoint and pricing settings; keep DLT/OTP/campaigns. Adapt known nested provider reports and do not convert unconfirmed sends to final failure. Preserve redacted delivery audit and counts.
2. Minimal operator backend and webhook/tests: delete reseller/billing/recharge integrations, keep connection endpoints with trusted origin and safe repeat registration; remove Razorpay SMS webhook. No platform-wide payment/OAuth changes.
3. Frontend: retain client tabs; remove recharge/financial displays/API/types, standalone operator SMS view/stock card; add Config connection panel and retained template-request handling; fix touched report parsing/polling, preview/schedule correctness where practical.
4. Parent integration: trim unapplied migration 237 SQL (no financial tables/views/columns), remove sms.recharge permission and stock scheduler/router/env wiring, update docs/contracts, verify no unwanted references, run tests/typecheck/lint and browser UI QA, obtain Python/TypeScript/security/SQL reviews.

## Interface contracts

- Client GET/sms/balance returns {sms_count}; status has enabled/connected/support contact (no price). Campaign preview returns counts/examples/exclusions (no money). Messages/reports/CSV never expose financial fields.
- Minimal operator retains GET/operator/clients/{id}/sms, PUT.../sms/key and POST.../sms/webhook. State: connected, key_masked, webhook_registered, webhook_error; count may be included but no money. Client key save remains operator-only; Developer key reveal remains owner-only by explicit user choice.
- Remove operator reseller mutations/account/credits/settings/profit/stock/payment routes and sms recharge routes. Template-request state management remains operator-only as needed for the retained UI.
- Bulk9 credentials continue in app_settings, guarded in FastAPI; migration 237 adds database-level restrictive policies protecting sms_/bulk9_ settings from direct authenticated table access. Service role remains able to access. No broad unrelated credential migration.
- Migration 237 is reportedly unapplied; verify read-only live metadata before trimming it. Never apply it in this task.

## Rulings

- The final approved scope keeps BOTH client DLT forms and OTP & Developer; earlier removal suggestions for those are superseded.
- Scope includes removing financial information from APIs/export/audit persistence, not merely hiding currency labels. Preserve delivery evidence, statuses, counts, provider request IDs and dedupe.
- Existing inspected delivery defects affecting touched code are fixed with documented fixtures; no unrelated platform refactor.
- Source tests are not proof of provider connectivity; no real provider test without separate authorization. Browser QA must use the UI test tenant or an explicitly isolated equivalent with mocked provider responses; never run plain uvicorn.
- Preserve all unrelated Razorpay OAuth and application work.

## Completion evidence

Record each slice's files and RED→GREEN tests below; no completion claim without final checks/reviews. Full backend baseline before cleanup: 4,627 tests + 19 subtests passed; frontend 16 helper tests/typecheck/lint passed, but inspection found provider fixture and UI defects.


## Implemented and verified — 31 October 2026

- Client: all five tabs retained, including DLT entity/sender/template forms and Excel imports, template requests, OTP and owner-only Developer key access. Balance shows SMS credits only. Campaign previews, reports, CSV and stored delivery events contain no monetary fields.
- Operator: removed standalone SMS reseller screens and stock cards; added masked API-key connection, webhook retry and paged template-request handling in client Configuration.
- Backend/schema: removed SMS billing/recharge/reseller modules, stock scheduler and `sms.recharge`; trimmed the unapplied migration, protected provider settings through restrictive database policies, and preserved unrelated payments/OAuth.
- Correctness: imported templates require explicit classification, promotional consent requires source and date, past schedules are rejected, nested provider report rows are flattened, and ambiguous sends remain recoverable without automatic resend. Invalid wallet SMS-count responses are rejected.
- Full backend run before upstream integration: **4,656 passed, 19 subtests passed** in 510.52 seconds. Frontend: **51 helper tests**, typecheck and scoped lint passed.
- SQL: migration executed only in a disposable local PostgreSQL 16 database; tenant isolation, protected settings, grants and write restrictions passed. Live Supabase was inspected read-only to confirm migration 237 was not applied.
- Browser: actual Next UI checked in isolated Chrome with local authentication/API fixtures representing the reserved UI test tenant; desktop/mobile Balance, five tabs, DLT forms, OTP UI and operator key-save/webhook-retry checked, with no page errors. The saved real UI test credentials were rejected; this does not establish live provider connectivity.
- Independent Python, TypeScript, general code, security and database reviews completed with no remaining findings after fixes.
- Fetched `origin/main` and rebased the SMS branch onto `e0780ad1`, preserving its event-loop/Supabase fixes; cleanup restored without conflicts. Post-rebase SMS, scheduler, settings, Supabase retry and event-loop regression tests: **104 passed** in 5.01 seconds. No incoming main commits remain outside the branch.

Implementation verification did not change the live database, provider accounts or send real SMS. Prem subsequently authorized committing, merging to main, pushing and deleting the SMS worktree. Migration 237 still requires separate application.
