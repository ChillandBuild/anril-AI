# Bulk9 API review and Anril integration notes

Saved 29 October 2026 (Asia/Kolkata). This single file preserves the full documentation-review findings, the complete 118-page inventory, the Fast2SMS email conclusions and the integration discussion. It contains no account passwords or live API keys.

## Conversation context and decisions

- Goal: offer SMS inside Anril using Bulk9/Fast2SMS reseller infrastructure, so clients do not need to open Bulk9 for their everyday SMS work.
- The discussion first investigated all 44 audited dashboard functions. The current direction is to start with functions that have usable documented APIs; complete dashboard parity is no longer the immediate requirement.
- Use Anril's own client login, leads, contact selection, campaign records and reports. Keep per-client Bulk9 credentials on Anril's backend, associated with the correct tenant. Operator setup matches Anril's existing operating model.
- Initial proposed scope: connect each client's key, add/import approved DLT details, fetch configured templates, select leads and variables, preview, send, show balance and delivery results. Scheduling, OTP and reseller automation can be selected in the implementation plan.
- No implementation approval or code change is implied by this research. No live sending, OTP, uploads, credit allocation or account mutation was tested in this review.
- The earlier 30% documented / 70% missing estimate was a rough, equally weighted count of dashboard features, not a measure of useful SMS workflow coverage. It should not guide the implementation decision, especially after the current documentation changes.
- The earlier reseller-video investigation sampled the full 25:53 timeline using 777 extracted frames grouped in contact sheets, enlarged selected frames and processed the soundtrack through speech recognition. It was not uninterrupted watching, direct listening or 777 individual detailed image reviews.
- Video findings included client-specific accounts/API access, operator credit allocation, support handled by the reseller and an example failed SMS that still incurred charges. Video example prices were historical illustrations, not current rates. Prepaid/postpaid labels did not establish payment collection.

## Fast2SMS email of 27 October 2026

The email is useful provider guidance but is not evidence of live-tested API behavior. Its 18 grouped topics are preserved below, with the current review's necessary distinctions.

| Topic | Provider reply and current interpretation |
|---|---|
| DLT entities | Add already DLT-approved entity details through DLT Manager APIs. Current request/response definitions exist; entity acceptance can still be pending. |
| Sender IDs | Individual and DLT-exported Excel/CSV import APIs are now documented. |
| Content templates | Individual and bulk import APIs are documented; approved-template listing supplies message IDs. Approval/rejection tracking is not established by that listing response. |
| New telecom template approval | No direct API; submit through the respective telecom DLT portal. |
| PE–TM binding | No API; complete it through the dashboard. |
| Smart OTP templates/settings | Sending uses an existing OTP template, supplied/generated code, length, expiry and variables. Template creation and general settings-management APIs are not thereby established. The email's illustrative otp_length=1 conflicts with the documented valid range 4–10. |
| OTP verify/resend | Both operations are documented, subject to time/attempt limits. |
| Address Book | No provider API; contacts/groups remain manual in Bulk9. Anril can independently use its existing leads and contacts for SMS recipients without syncing Bulk9's Address Book. |
| Scheduled SMS | schedule_time enables scheduling on documented send forms. Queue listing/cancellation/rescheduling remain unconfirmed. |
| Transaction history | No complete wallet transaction-history/export API. sms_details supplies message-level charges after submission, not the entire ledger or an exact pre-send quotation. |
| Reseller and plans | Account management, balances and credit allocation/debit are documented. Expiry changes need a known plan_id. The pricing-update endpoint explicitly excludes existing SMS plans; it supports RCS/WhatsApp. |
| Client API keys | Access/regeneration/enable/disable are manual dashboard operations; no automatic key retrieval or provisioning contract is documented. |
| API security/low balance | Low-balance notifications are manual; IP restriction/history APIs remain unconfirmed. |
| Webhooks | Configuration APIs and delivery callbacks exist. Historical attempts, errors and replay APIs remain unconfirmed; request definitions have incomplete response contracts. |
| Account settings | Profile, billing/GST, password, login security and duplicate-number preferences are dashboard-managed; API support remains unconfirmed. |
| Report exports | Delivery data can be retrieved or received by webhook. Dedicated provider-generated SMS/OTP/transaction export APIs remain unconfirmed. Anril could export the data it stores. |
| Pre-send quotation | Provider requested expected monthly volume and a contact number for discussion; no exact quotation API was supplied. |
| Fast2SMS compatibility | Separate environments and credentials. Do not substitute Fast2SMS endpoints or keys for Bulk9 unless explicitly supported. Private/partner API access requires further technical confirmation. |

A Google Meet had been booked during the prior discussion. The technical follow-up should seek working examples only for dependencies retained in the chosen scope, especially approval-state visibility, client-key provisioning, plan-ID discovery and exact pre-send pricing.

## Contents

- [Current full-review conclusions](#current-review)
- [SMS, DLT, OTP, wallet and errors](#sms-otp-review)
- [Complete reseller reference review](#reseller-review)
- [Complete WhatsApp reference review](#whatsapp-review)
- [Complete webhook reference review](#webhooks-review)
- [All 118 public-reference pages](#page-inventory)
- [Coverage verification](#coverage)

The detailed sections below are preserved from the completed review. Backticked source/archive filenames describe the original research evidence; this file's conclusions, operation inventories and official links are included here and do not require those external local files.


---

<a id="current-review"></a>

## Bulk9: full current documentation review for Anril

Reviewed 29 October 2026, Asia/Kolkata.

### Sources and scope

The two sources are exactly those Fast2SMS named in its email:

1. [Bulk9 API Documentation](https://bulk9.com/docs/). This page embeds [the Bulk9 user API reference](https://docs.bulk9.com/reference/authorization?domain=bulk9.com). The current sidebar exposes **118 unique pages**, including section wrappers. All complete narratives and available request/response definitions were reviewed, not just the index or summaries.
2. [Bulk9 Reseller API Documentation](https://bulk9.com/reseller/docs/). The complete reference was reviewed: **10 URL patterns and 14 documented method/path variants**, plus its linked Postman collection's visible inventory. That collection adds no operation and omits three operations now present in the HTML reference.

| User-reference section | Unique pages reviewed |
|---|---:|
| Authorization | 1 |
| SMS, DLT setup, delivery reports and analytics | 19 |
| Smart OTP | 3 |
| WhatsApp | 73 |
| New webhook system: SMS, OTP, WhatsApp, RCS | 20 |
| Wallet | 1 |
| Errors | 1 |
| **Total** | **118** |

The 118 pages include **96 pages with OpenAPI operation definitions** and 22 narrative/section pages. Repeated template variants and wrappers mean those 96 pages are not 96 independent API functions: their definitions contain 64 distinct composed method/path combinations. The reseller reference is separate from this count. [Complete linked page inventory](#page-inventory) and [machine-readable coverage](#coverage) preserve the scope and saved sources.

Reading documentation does not prove live API behavior. No live messaging, OTP, account creation, template/proof upload, credit change, payment, account login or configuration mutation was performed. No Anril project code was changed. All findings are limited to the material exposed by these two current references; undocumented private/partner operations are not assumed.

### Main corrections and findings for SMS integration

#### Earlier missing DLT definitions are now present

The current reference supplies working-shaped operation definitions for all seven pages previously found incomplete:

| Function | Documented method/path |
|---|---|
| Fetch configured senders and approved templates | GET /dev/dlt_manager |
| Add an already DLT-approved entity | POST /dev/dlt_manager/add_entity |
| Add an approved sender | POST /dev/dlt_manager/add_sender |
| Import approved senders from DLT export | POST /dev/dlt_manager/add_sender_excel |
| Add an approved content template | POST /dev/dlt_manager/add_template |
| Import approved templates from DLT export | POST /dev/dlt_manager/add_template_excel |
| Fetch a sending request's delivery report | GET /dev/dlr/{request_id} |

This supports the previous feature list at the documentation level. The old conclusion that these pages contain placeholder operations is no longer current. It does not establish a date when the service changed, because documentation timestamps are inconsistent across views.

#### Template import and approval tracking remain different capabilities

Entity creation's success example says pending approval. Sender-file import also illustrates pending approval. The sender/template fetch returns sender/entity information and approved template records with `message_id`, wording and variable count. It provides no pending/rejected status or rejection reason. Template creation/import success does not return the sending message ID; fetch it separately. Automatic submission of new wording to telecom DLT operators and PE–TM binding are not operations in this reference; the support email confirms their manual process.

Bulk imports consume HTTPS public URLs to original DLT-exported .xlsx/.csv files, rather than direct multipart file bodies. Original export structure must be preserved. Entity proof requires 1–5 public HTTPS file links, with stated format and size limits.

#### Sending, costs and history have precise limits

- Configured-template sending uses `route=dlt` and a Bulk9 message ID; manual sending uses `route=dlt_manual`, full approved wording and DLT IDs. Batch personalized sending uses `/dev/custom` with per-message records.
- `schedule_time` is defined for the single/GET send forms; the batch schema does not include it. Timezone, queue listing, cancellation and rescheduling are unspecified.
- `sms_details=1` describes charges returned after a send request; it is not a pre-send quotation. Its detailed result fields are not included in the minimal send response schema.
- Logs permit at most three-day query windows; summaries at most 30-day windows; both specify start dates within the last year. Per-request delivery fetch covers the last seven days.
- UDFs support correlation, not a documented idempotency guarantee. Retry safety, throughput and batch size limits need validation.
- The manual overview and copied field descriptions conflict about whether a sender must first be saved in DLT Manager and whether stored IDs may be omitted. Test the intended route before relying on that shortcut.
- Language/Unicode appears in error/report text, but the SMS send schemas do not define a language-selection field. Exact Tamil/Unicode selection and segment charging need confirmation rather than an assumed request parameter.

#### OTP and webhook caveats

OTP send, verify and resend are documented; sending requires an existing `otp_id`, with no OTP-template creation/listing operation in the reference. OTP length is 4–10, default 6; expiry 1–10080 minutes, default 15. The email's illustrative `otp_length=1` is outside that documented range. Resend is within 10 minutes, at most 5 attempts; exact verification-attempt limits are unspecified.

The new webhook API documents list/create/update/soft-delete requests for all four services and custom outgoing authentication headers. All 16 operations lack response-body schemas and error examples. Callback retries/acknowledgment/ordering/replay are underspecified; the existence of configuration APIs does not remove the need for a controlled integration test. WhatsApp Meta-shaped body mode does not establish preservation of Meta's original signatures.

#### Reseller account and credit caveats

Create/list/enable/disable clients, reseller/client balances, SMS allocation and withdrawal, and plan expiry changes have documented operations. A new allocation can set SMS selling rate and expiry. Existing SMS plan repricing is explicitly unsupported; existing RCS/WhatsApp repricing has different rules. The email's broad pricing statement should not be applied to SMS.

No user-key retrieval/rotation operation or key in account-creation response is documented. Expiry and RCS/WhatsApp repricing require `plan_id`, which the docs tell the operator to obtain from the panel; no plan-list API or new plan ID in add-credit response is provided. RCS/WhatsApp debit withdraws the whole channel balance. Credit allocation is distinct from customer payment collection or purchasing reseller stock.

### Other reference areas reviewed

WhatsApp covers operations on existing business accounts/numbers/profiles; simple and Meta-shaped session/template sending; text, authentication, media, location, catalog, multi-product, carousel, coupon, limited-offer, CTA and Flow template operations; media; chat QR codes; recipient blocking; legacy callbacks and reports. These do not establish embedded signup, phone registration/migration or new-business onboarding. Template creation is not approval, and an existing Flow ID is not a Flow-definition creation API. RCS has callback configuration here, without a documented complete RCS sending/onboarding workflow.

Detailed WhatsApp field/schema limitations are in the separate report below. The documentation contains several copied response types and conflicting examples; those are documentation defects, not observed runtime failures.

### Detailed review evidence

- [SMS, DLT, OTP, wallet and errors: all 25 pages](#sms-otp-review).
- [Reseller reference: all sections, fields, responses, examples and Postman inventory](#reseller-review).
- [WhatsApp reference: all 73 pages](#whatsapp-review).
- [Webhook system: all 20 pages, 16 operations and 12 payload examples](#webhooks-review).
- [Complete 118-page linked inventory](#page-inventory).
- [Coverage verification and source file mapping](#coverage).

The review provides an evidence base for choosing implementation scope; a subsequent implementation plan should separate documented requests, manual setup, incomplete response contracts and live-tested behavior.

---

<a id="sms-otp-review"></a>

## Bulk9 SMS, DLT, OTP, wallet and errors — complete documentation review

Reviewed 29 October 2026 (India). Scope: all 25 current pages in Authorization, SMS API (19), OTP API (3), Wallet Balance API and Error Codes, including wrapper pages. Full Markdown narrative and OpenAPI JSON were read, including nested batch fields, response examples, errors and numeric constraints. Sources are saved under `sms-otp/`; `inventory.json` records the authoritative sidebar inventory. This is documentation review, not live API verification.

Entry: [Bulk9 API documentation](https://bulk9.com/docs/), embedding [the reference](https://docs.bulk9.com/reference/authorization?domain=bulk9.com). Base host in the reviewed operation definitions is `https://bulk9.com`. Requests require the account key in the `Authorization` header. No bearer prefix is specified. No key provisioning endpoint is documented here.

### Complete page and operation inventory

| Page | Method/path | Fields, result and limitation |
|---|---|---|
| [Authorization](https://docs.bulk9.com/reference/authorization?domain=bulk9.com) | Narrative | Obtain a key from Dev API and put it in the Authorization header. |
| [DLT SMS](https://docs.bulk9.com/reference/dlt-sms?domain=bulk9.com) | GET /dev/bulkV2 | route=dlt, sender_id, provider message ID, variables_values and numbers; optional schedule_time, sms_details and udf1–3. |
| [DLT SMS Single](https://docs.bulk9.com/reference/dlt-sms-single?domain=bulk9.com) | POST /dev/bulkV2 | Same fields in JSON; message is an integer provider message ID here, unlike GET's string. Returns return, request_id and message. |
| [DLT SMS Multiple](https://docs.bulk9.com/reference/dlt-sms-multiple?domain=bulk9.com) | POST /dev/custom | route=dlt and requests[]; each item requires sender_id, message, variables_values and numbers; UDFs exist both per item and at top level. No precedence, batch maximum or throughput contract. |
| [DLT Manual overview](https://docs.bulk9.com/reference/dlt-manual-api?domain=bulk9.com) | Narrative | Directly passes approved DLT details; incorrect details/text can fail without refund/support. Says details need not be saved in DLT Manager. If saved, matching text can allow omission of entity_id/template_id, conflicting with required flags below. |
| [DLT Manual](https://docs.bulk9.com/reference/dlt-manual?domain=bulk9.com) | GET /dev/bulkV2 | route=dlt_manual, full message, sender_id, entity_id, template_id and numbers; scheduling/details/UDFs optional. |
| [DLT Manual Single](https://docs.bulk9.com/reference/dlt-manual-single?domain=bulk9.com) | POST /dev/bulkV2 | Same JSON contract, full text rather than provider message ID. Still requires prior telecom DLT approval. |
| [DLT Manual Multiple](https://docs.bulk9.com/reference/dlt-manual-multiple?domain=bulk9.com) | POST /dev/custom | route=dlt_manual; each request requires sender_id, full message, entity_id, template_id and numbers; top-level/per-item UDFs. |
| [DLT Manager overview](https://docs.bulk9.com/reference/dlt-manager?domain=bulk9.com) | Narrative | Add/fetch already DLT-approved entity, sender and content-template details and obtain provider message IDs. |
| [View Sender/Template](https://docs.bulk9.com/reference/view-sender-1?domain=bulk9.com) | GET /dev/dlt_manager | type=sender (default) or template. Returns sender_id, entity_id, entity_name and, for template, templates[] containing message_id, message and var_count. No pending/rejected status, rejection reason, standalone entity list, pagination or full DLT template ID is specified in this response. |
| [Add Entity](https://docs.bulk9.com/reference/add-entity?domain=bulk9.com) | POST /dev/dlt_manager/add_entity | entity_name, entity_id, screenshot_links required. 1–5 HTTPS public proof-file URLs, stated max 20 MB each. Accepts jpg/jpeg/png/gif/pdf/doc/docx/odt. Success example says entity pending approval; acceptance is not readiness to send. |
| [Add Sender](https://docs.bulk9.com/reference/add-sender-id?domain=bulk9.com) | POST /dev/dlt_manager/add_sender | Required approved entity_id and sender_id (3–6 characters); optional screenshot_links up to five public proof URLs. |
| [Add Senders Excel](https://docs.bulk9.com/reference/add-sender-id-excel?domain=bulk9.com) | POST /dev/dlt_manager/add_sender_excel | entity_id and sender_excel HTTPS URL of DLT-exported .xlsx/.csv. Preserve the original export format. Success example says uploaded, pending approval. |
| [Add Content Template](https://docs.bulk9.com/reference/add-conten-template?domain=bulk9.com) | POST /dev/dlt_manager/add_template | Required entity_id, sender_id array, template_id string (described as 19 digits), message_text matching approved wording with {#var#}. Optional template_type n=Service Implicit, y=Service Explicit/Promotional. Success returns return/message, not a message ID; fetch configured templates separately. |
| [Add Templates Excel](https://docs.bulk9.com/reference/add-content-templates-excel?domain=bulk9.com) | POST /dev/dlt_manager/add_template_excel | entity_id and content_excel HTTPS URL of original DLT-exported .xlsx/.csv; optional template_type n/y. Returns count in message, not item-by-item status or template IDs. |
| [Delivery Report overview](https://docs.bulk9.com/reference/delivery-fetch-api?domain=bulk9.com) | Narrative | Real-time callbacks or per-request fetch for last seven days. Callback cross-link uses an older slug, so use current Webhook(New) pages. |
| [Fetch Reports Manually](https://docs.bulk9.com/reference/fetch-delivery-reports?domain=bulk9.com) | GET /dev/dlr/{request_id} | Last seven days. Data includes request ID, route, recipient status/description, sender, language, character/SMS count, debit, UDFs and sending time. Status enum lists Delivered/Failed/Sent. 404 means missing report or only invalid numbers, not a proven delivery failure. |
| [SMS Analytics](https://docs.bulk9.com/reference/sms-analytics?domain=bulk9.com) | Empty heading wrapper | Read; no independent operation or narrative. |
| [SMS Logs](https://docs.bulk9.com/reference/sms-analytics-api?domain=bulk9.com) | GET /dev/sms_logs | Required from/to YYYY-MM-DD; at most three-day interval, start within previous year. page>=1, limit 1–1000, default15. Per-recipient statuses/charges, UDFs, send and delivery timestamps, plus pagination. |
| [SMS Summary](https://docs.bulk9.com/reference/sms-logs-summary?domain=bulk9.com) | GET /dev/sms_summary | Required from/to, max30-day interval, start within previous year; sent/delivered/pending/failed/blocked/error counts. |
| [Send OTP](https://docs.bulk9.com/reference/send-otp?domain=bulk9.com) | POST /dev/otp/send | Required mobile (10 Indian digits) and existing otp_id. Optional provider-generated or supplied OTP, length4–10 (default6), expiry1–10080 minutes (default15), variables_values and UDFs. {otp} can repeat code in variables. 200 returns request_id; 400 invalid parameters/template; 401 invalid key. |
| [Verify OTP](https://docs.bulk9.com/reference/verify-otp?domain=bulk9.com) | POST /dev/otp/verify | mobile and otp; limited attempts with no exact verification-attempt count documented. 400 invalid/expired/max attempts; 404 missing or already verified. |
| [Resend OTP](https://docs.bulk9.com/reference/resend-otp?domain=bulk9.com) | POST /dev/otp/resend | mobile; last OTP, within10 minutes, maximum5 resends. 404 no earlier request; 400 limit/window expired. |
| [Wallet](https://docs.bulk9.com/reference/wallet-balance?domain=bulk9.com) | POST /dev/wallet | Authorization only; return, wallet and sms_count. No financial transaction ledger or collection operation. |
| [Error Codes](https://docs.bulk9.com/reference/error-code-list?domain=bulk9.com) | Narrative table | Distinguishes HTTP status from provider status_code. Includes missing/invalid sender/message/route/language/numbers, disabled/invalid keys/accounts, IP blacklist, insufficient wallet, invalid template/variables, DLT blacklist, legacy API, spam, OTP KYC and numeric-only legacy OTP variables. |

Nineteen pages contain operation definitions; six are narrative/empty wrappers. Deduplicating same method/path across DLT routes gives 16 distinct method/path operations. Route variants retain different required fields and must not be collapsed into one request schema.

### What is newly resolved versus the 24 October saved review

All six previously incomplete DLT Manager operation pages now provide real Bulk9 paths, required fields, response examples and error contracts. The per-request delivery-fetch operation is also now defined as GET /dev/dlr/{request_id}. The current public documentation therefore resolves the earlier missing endpoint problem for these seven pages. This establishes documentation availability, not proof of operation in the user's account.

### Limits and unanswered integration contracts

- Telecom DLT registration/approval and PE–TM binding are not provided by these API operations; the support email separately confirms their manual workflow.
- Entity acceptance can return pending. Sender Excel import explicitly shows pending. The documented sender/template fetch returns approved template records without status/rejection fields, so it is not a complete approval tracker. No rejection callback contract, standalone entity-status endpoint, or update/delete DLT entity/sender/template operation is documented.
- Imports require provider-fetchable HTTPS file URLs; they do not accept direct multipart file uploads in the documented JSON requests. The documentation does not define authenticated or expiring-file URL support, fetch timing or file retention.
- schedule_time is documented on single/GET sending routes, not in either /dev/custom batch schema. Date string and Unix formats are described, but timezone, maximum advance interval, listing, cancellation and rescheduling are not established.
- sms_details describes charges returned on sending, not an exact quotation before submission. Its extra response fields are not actually included in the minimal sending response schema. Treat expected values as needing a real account response.
- UDFs correlate Anril and provider requests; they are not documented idempotency keys. No duplicate suppression, retry guarantee, rate-limit headers or batch size limit is documented.
- The manual overview says sender/template details can be passed directly without DLT Manager, but copied sender descriptions say the header must first be added in DLT Manager. The overview also allows omission of IDs for saved templates while schemas require them. Confirm the direct route in a controlled test.
- English/Unicode support is referenced by error codes and returned sms_language, but the reviewed SMS sending schemas expose no language/encoding selection parameter. Do not promise a specific Tamil/Unicode configuration until its selection and segment accounting are confirmed.
- OTP requires an existing otp_id. No OTP-template creation/listing or verification-limit configuration API appears in this scope. The support email's sample otp_length=1 is outside the documented4–10 range; use the documentation's valid range.
- Broad error text says HTTP400/401, but individual operations also define404. Codes401–411 in the provider table are application errors, not HTTP statuses. Error shapes vary between return/message, success/data and return/errors_keys/errors.

### Documentation inconsistencies to accommodate in a future implementation

Sending response schema types return as boolean but gives string default true; message is an array with a string default. Logs document success as string but example boolean; mobile string vs numeric example; amounts numeric schema vs string example; Unix timestamp numbers vs date-time strings; pagination strings vs numeric examples; nullable previous URL not reflected in type. Wallet return is string with description true and sms_count integer has an empty string default. Template validation example says 'Invalid sender emails provided', although the field is sender IDs. These are documentation defects, not verified service failures.

### Anril interpretation

Documented client workflow can include uploading approved entity proof, importing approved senders/templates, fetching usable template IDs and wording, mapping Anril leads to variables, sending, showing balance, and displaying callback/log/report results. Operator setup still connects the account key and handles external approvals/binding. Approval state must remain separate from 'import accepted' and 'template visible for sending'. No live sending, OTP, uploads, account creation or credit changes were performed during this review.

---

<a id="reseller-review"></a>

## Bulk9 reseller documentation: complete review

Reviewed 29 October 2026 (India). Primary source: [Bulk9 Reseller API documentation](https://bulk9.com/reseller/docs/). Also inspected its [official linked Postman collection](https://www.postman.com/bulk9-reseller/bulk9-reseller/collection/bmfb4e2/bulk9-reseller-api) in the public browser viewer. All findings below describe documentation, not verified service behavior. No Bulk9 API requests, logins, messages, user creation, credits, or payments were performed.

The reseller API documents account management and allocation of existing channel balances. It does not document buying Bulk9 balance, charging Anril customers, issuing customer API keys, provisioning WhatsApp/RCS senders, or a complete automated plan-management workflow.

### Coverage and exact operation inventory

Read every page section, field table, success/error response and language example, including the added debit, expiry and pricing sections. There are **10 distinct URL patterns and 14 method/path variants**, or 15 business actions if channel-specific credit, debit and pricing actions are counted separately. Base URL: `https://bulk9.com/api/reseller`.

| URL suffix | Documented methods | Purpose | Inputs besides authentication |
|---|---|---|---|
| `/balance-check` | GET, POST | Reseller balances | None |
| `/balance-check/{user_name}` | GET, POST | One user's balances | Username in path |
| `/enable/{username}` | GET, POST | Enable user account | Username in path |
| `/disable/{username}` | GET, POST | Disable user account | Username in path |
| `/list-user` | GET | All reseller users | None; no pagination/filter parameters documented |
| `/create-user` | POST | Create reseller sub-user | Required `name`, `username`, `password`; optional `email`, `mobile` |
| `/add-credit/{username}` | POST | Add SMS/RCS/WhatsApp user plan/credits | Channel-specific fields below |
| `/debit-credit/{username}` | POST | Withdraw user credits to reseller | Channel-specific fields below |
| `/update-expiry/{username}` | POST | Change existing plan expiry | Required `plan_id`, `expiry_date` |
| `/update-pricing/{username}` | POST | Change existing RCS/WhatsApp sell prices | Channel-specific fields below; SMS unsupported |

Authentication is the reseller account API Authorization Key, passed **raw**, without a documented `Bearer` prefix. GET uses query parameter `authorization=YOUR_API_KEY`; POST uses header `Authorization: YOUR_API_KEY`. The overview links [Dashboard → developer API](https://bulk9.com/dashboard/dev-api) for the account key. No scopes, key issuance/rotation endpoint, rate limits, idempotency keys, request IDs or versioning policy are described. The official page includes a real-looking public example token; it has been redacted from saved source snapshots and is not reproduced here.

POST examples use form fields. Create-user cURL uses multipart `-F`; its other language examples use `application/x-www-form-urlencoded`. Credit/debit/expiry/pricing cURL examples use `-d` form data. JSON request-body support is not documented. Prefer an explicitly encoded server-side form request when implementation is approved; keep TLS certificate checking enabled and credentials out of browser code and request logs.

### Responses and account fields

**Reseller balance** success example:

```json
{"return":true,"sms_balance":"500.0000","sms_count":48000,"rcs_balance":"250.0000","rcs_pending":"100.0000","wa_balance":"1000.0000","wa_pending":"400.0000"}
```

`sms_balance` is available SMS ₹ balance; `sms_count` is available SMS message count. `rcs_balance` and `wa_balance` are **total** reseller channel balances, including balances already assigned to users. `rcs_pending` and `wa_pending` are the unassigned, assignable amounts. Do not treat total RCS/WhatsApp balance as money immediately available for another allocation. No equivalent SMS pending field is documented.

**User balance** success example:

```json
{"return":true,"sms_balance":"100.0000","sms_count":976,"rcs_balance":"50.0000","wa_balance":"200.0000"}
```

No per-plan rows, IDs, prices, expiry dates or pending values are returned in this example. Reseller field descriptions explicitly establish currency meaning; the user response is supplied without a separate response-field table.

**Enable/disable** return `return:true` and a human-readable success `message` identifying enabled/disabled status. Username is required; `user33` is the sample. No state enum or already-enabled/disabled behavior is documented.

**List users** returns `return:true` and `users[]`. Each example row has string fields `username`, `name`, `email`, `mobile`, `status` (`"active"` example) and `credit` (`"₹ 12.5000"` example). No user ID, API key, channel breakdown, plan ID, pagination, sorting, count or complete status enum is described. `credit` is a formatted string and its channel scope is unspecified; use the balance endpoint for channel accounting.

**Create user** requires a unique `username`, a display `name` and `password`; `email`/`mobile` are optional. Password rules, username length/character rules, contact formats, uniqueness scope and duplicate-user handling are unspecified. Its printed success object contains `return:true` and `message:"User created successfully"` but has an invalid trailing comma. No API key, user ID, channel credentials or plan is shown. Therefore the documented response does not support automatically obtaining the new user's sending key. A sample password is only an example and should never become a production default.

### Add credit: complete field contract

`POST /add-credit/{username}` requires the reseller Authorization header. Each successful channel example is:

```json
{"return":true,"message":"Plan added successfully","status":true}
```

No created `plan_id`, before/after balance, allocation ID, invoice ID or credential appears in that response.

| Channel | Required body fields | Optional body fields | Published example values |
|---|---|---|---|
| SMS | `channel=sms`, `no_of_sms`, `per_sms_cost`, `type_of_invoice` | `expiry_date` | `100`, `0.11`, `prepaid` |
| RCS | `channel=rcs`, `amount`, `per_sms_cost`, `type_of_invoice` | `expiry_date` | `500`, `0.50`, `prepaid` |
| WhatsApp | `channel=whatsapp`, `amount`, `per_sms_cost`, `per_marketing_cost`, `type_of_invoice` | `per_session_cost`, `expiry_date` | `1000`, `0.35`, `0.50`, `prepaid`; optional session `0.03` |

For SMS, `no_of_sms` is message quantity and `per_sms_cost` is per-message price. For RCS, `amount` is total ₹ to credit and `per_sms_cost` is per-RCS-message price. For WhatsApp, `amount` is total ₹ to credit, `per_sms_cost` is described as **utility** message price, `per_marketing_cost` as marketing message price and `per_session_cost` as a session API cost override. Do not interpret RCS/WhatsApp `amount` as a message count.

`type_of_invoice` accepts `prepaid` or `postpaid` on all three channels. The operational, billing and overdraft effects of postpaid are not explained. Optional `expiry_date` is `YYYY-MM-DD`, defaulting to one year from now. The page does not define timezone or cutoff time, amount/price precision, minimum/maximum allocations, integer constraints, buy-cost validation for creation, duplicate request behavior or insufficient-balance errors per channel. Example prices are illustrations, not a Bulk9 price list or a quote.

### Debit credit: complete field contract

`POST /debit-credit/{username}` withdraws credits **back to the reseller**, according to its description; it is not documented as a bank refund or customer payment reversal.

| Channel | Required body | Documented effect |
|---|---|---|
| SMS | `channel=sms`, `credit_sms` | Withdraw specified SMS quantity; example `credit_sms=50` |
| RCS | `channel=rcs` | **Withdraw entire RCS wallet balance** |
| WhatsApp | `channel=whatsapp` | **Withdraw entire WhatsApp wallet balance** |

SMS success example has `return:true`, success `message`, and numeric `amount_debited:5.50`. RCS success has the same shape with `amount_debited:250.00`; no separate WhatsApp response object is printed. There is no documented partial RCS/WhatsApp withdrawal field. No plan selector, pricing basis for SMS withdrawal, expired/consumed credit rules, zero-wallet behavior or concurrency protection is specified. `amount_debited` is numeric in these examples, while balance fields are decimal strings.

### Expiry and pricing: exact restrictions

**Change expiry:** `POST /update-expiry/{username}`, required `plan_id` and `expiry_date` (`YYYY-MM-DD`). Applies to SMS, RCS and WhatsApp plans; date must be today or later, and the plan must belong to the username. Example body is `plan_id=123&expiry_date=2027-09-24`; success includes `return:true`, `status:true`, success `message`, numeric `plan_id:123`, and `expiry_date:"2027-09-24"`.

The page explicitly instructs the operator to obtain `plan_id` from the user's credit/plan list **in the reseller panel**. It documents no plan-list/discovery API, and add-credit does not return a plan ID. Expiry and repricing automation therefore have a documented discovery gap.

**Update pricing:** `POST /update-pricing/{username}` changes sell prices only for **RCS and WhatsApp**. **SMS plan pricing is explicitly unsupported via this API.** New prices cannot be below the reseller buy cost, and the plan must still have available amount greater than zero.

| Channel | Required body fields | Aliases and meaning |
|---|---|---|
| RCS | `channel=rcs`, `plan_id`, `per_message_cost` | `per_sms_cost` is an alias for per-message price |
| WhatsApp | `channel=whatsapp`, `plan_id`, `per_auth_utility_cost`, `per_marketing_cost`, `session_api_cost` | `per_sms_cost` aliases auth/utility price; `per_session_cost` aliases session API price |

RCS example uses `plan_id=123&per_message_cost=0.50`. WhatsApp example uses `plan_id=123&per_auth_utility_cost=0.15&per_marketing_cost=0.95&session_api_cost=0.02`. Success examples contain `return:true`, `status:true`, and a channel-specific success `message`, with no resulting prices. WhatsApp session price is optional when adding credit but **required** in the repricing table. Creation calls its price utility-only while repricing calls it auth/utility; confirm authentication billing semantics. No buy-cost lookup API, effective-time rule, historical usage treatment, alias precedence, currency precision or below-buy-cost error object is documented.

### Errors and example quality

The page states success is HTTP 200. Its prose says errors are 400 or 401, but its table also includes **403**. Handle transport status and JSON body separately: JSON `status_code` is an application code, not necessarily the HTTP status.

| HTTP response code | JSON/application status code | Meaning |
|---|---|---|
| 401 | 412 | Invalid authentication; check Authorization Key |
| 403 | 415 | Account disabled |
| 403 | 428 | Account blocked |
| 403 | 413 | Authorization Key disabled |
| 400 | 419 | Invalid parameters |
| 401 | 429 | Not enough SMS |

The only full error object is `{"return":false,"status_code":412,"message":"Invalid Authentication, Check Authorization Key"}`. The table's application `429` means insufficient SMS, **not a documented HTTP rate-limit response**. No RCS/WhatsApp insufficient-funds errors, duplicate-user errors, missing-plan errors, expiry validation errors, buy-price rejection errors, partial failure shape, retry guidance or rate-limit headers are defined. `status` is present on add/expiry/pricing success examples but absent on others; require `return` and validate each endpoint's response rather than assuming one uniform schema.

All code tabs were reviewed: cURL, PHP, Java, C#, C, Python, Ruby, JavaScript and NodeJS. The first six account endpoints have these examples; the four later management sections provide cURL examples only. Specific defects to avoid copying:

- PHP and Ruby examples disable TLS certificate verification.
- User-balance GET Ruby sample has a malformed URI and `exaggerated_code` instead of `authorization`.
- User-balance POST PHP sample omits the Authorization header.
- Enable/disable POST PHP header arrays use colon syntax inconsistent with valid PHP array entries.
- Create-user success example is invalid JSON because of the trailing comma; create-user request examples disagree on multipart versus URL-encoded forms.
- Examples generally print the response without confirming a successful API `return`, do not supply a reliable retry policy, and are not production-ready clients.

### Official linked Postman comparison

The rendered public collection exposes **11 request entries**: GET/POST Reseller Balance, GET/POST User Balance, GET List User, POST Create User, POST User Add Credit, GET/POST User Enable, GET/POST User Disable. Thus it adds **zero operations** beyond the HTML page and omits the newer debit-credit, update-expiry and update-pricing entries. The collection overview displays a June 27, 2025 update timestamp. Its request detail/body panels did not populate useful field content in the public viewer; only the visible operation inventory is verified here, not full collection equivalence. No collection request was sent, run, imported, forked or edited. Treat current official HTML as the fuller documented operation set.

### Implications for Anril and remaining questions

These are integration conclusions from the documented contract, not promises about live behavior:

1. Keep reseller authentication in the operator/backend boundary. Map each Anril tenant explicitly to its Bulk9 username; users must not choose another tenant's username or plan ID. Use POST for enable/disable because those documented GET routes change state.
2. Track SMS quantity separately from RCS/WhatsApp ₹ wallets, and distinguish reseller total from pending assignable money. Decimal-string balances and numeric debit amounts need deliberate decimal handling.
3. Treat add-credit as provider allocation/plan creation. Customer checkout, successful payment verification, taxes/invoices and top-up reconciliation need a separately designed Anril payment flow. This page does not establish that calling add-credit charges a payment method, nor how reseller funds are purchased.
4. Automating customer setup remains incomplete: create-user returns no sending key; no key retrieval/rotation, channel enablement, RCS agent or WhatsApp WABA/number provisioning appears here. A user account is not documented as a ready-to-send channel account.
5. Do not expose a partial RCS/WhatsApp refund control backed by debit-credit; the documented endpoint empties the entire channel wallet. Any withdrawal workflow needs clear amount preview and operator control.
6. Expiry/repricing initially require manually recorded plan IDs unless Bulk9 supplies a discovery API. Buy-cost discovery and the positive-balance restriction also need confirmation before repricing is automated.
7. Financial mutations have no documented idempotency mechanism or transaction history. A timeout after allocation cannot safely trigger an automatic blind retry; reconcile outcome before repeating.

**12 unresolved questions to Bulk9:** (1) How is a new user's sending API key provisioned/retrieved/rotated? (2) Is there a supported plan-list API or add-credit response that returns `plan_id`? (3) How are reseller balances purchased and payments confirmed? (4) What exactly do prepaid/postpaid change? (5) How are reseller buy costs obtained and validated at creation/update? (6) Are authentication and utility charged identically, and what does session API cost cover? (7) What are decimal precision/minimums and amount/quantity limits? (8) Which timezone/cutoff and expiry rules apply? (9) How are SMS debit prices and multi-plan balances selected, and what happens to expired/used credits? (10) What are idempotency, audit-history and reconciliation options after a timeout/concurrent credit change? (11) What are endpoint-specific errors/rate limits, and are POST read responses identical to GET? (12) What channel-provisioning, sender onboarding and reseller/white-label rights are separately required?

Saved evidence: `reseller-source.redacted.html` (all HTML, example credential removed), `reseller-source.redacted.txt` (full extracted text with credential removed), `reseller-source-metadata.json`, and `reseller-postman-inventory.txt`. No project code changed.

---

<a id="whatsapp-review"></a>

## Bulk9 WhatsApp API — full reference review

Reviewed 29 October 2026, India time. Scope: every current page in the **WhatsApp API** category of the official [Bulk9 API reference](https://docs.bulk9.com/reference/authorization?domain=bulk9.com), embedded by [Bulk9 Docs](https://bulk9.com/docs/). All requests were public documentation GETs; no account/API calls, messages, configuration changes or logins were made.

### Coverage and evidence

**73 of 73 current WhatsApp-category pages retrieved and read completely: 61 endpoint pages, 11 empty section wrappers, and one panel setup page with a webhook example.** No WhatsApp page is missing. The 61 endpoint pages are documentation views, not 61 distinct API routes: many views use the same method and path with different payloads.

Discovery used both current `llms.txt` and the HTML `ssr-props.sidebar` tree. The sidebar includes wrapper pages omitted by the LLM index. Every page was downloaded using `https://docs.bulk9.com/reference/SLUG.md?domain=bulk9.com`; the domain parameter pins the example API server to `https://bulk9.com`. The embedded OpenAPI JSON, complete narratives, request examples, parameter definitions, schemas and response examples were read. The site's browser fetch tool failed; curl retrieved all 73 pages successfully (HTTP 200). An earlier Python-urllib attempt returned 403 and is retained separately, not counted as successful retrieval.

Local evidence:

- `whatsapp/inventory.json`: complete current sidebar records, including wrappers.
- `whatsapp/retrieval-curl.json`: successful page retrieval manifest.
- `whatsapp/SLUG.md`: full fetched narrative and OpenAPI for each page.
- `whatsapp/parsed-endpoints.json`: full parsed per-page operations, parameters, request bodies and responses.
- `whatsapp/schema-audit.md`: readable field-level audit of every request and response schema (2,516 lines), including required fields, enum values, defaults, declared limits and shared schemas.
- `whatsapp/navigation.html`, `whatsapp/navigation.json`, `whatsapp/llms.txt`: discovery evidence.

### What the API supports, and what that means

The documentation covers operating **existing WhatsApp Business Accounts (WABAs)** and their existing phone-number IDs: read number/account information, edit a business profile, send messages, create/edit/read/delete WhatsApp templates, upload media, create chat-opening QR codes, block recipients, configure the older webhook setting, and read reports/logs.

It does **not document an end-to-end onboarding API** for creating or connecting a WABA, launching Meta Embedded Signup, registering/migrating a phone number, requesting/verifying a phone registration OTP, supplying a number PIN, linking a business portfolio, or obtaining an account's underlying Meta credentials. A phone record's `last_onboarded_time` is information about an existing number, not an onboarding operation. A QR code starts a customer chat with an existing number; it does not connect or sign up a business account.

**Template creation is present. Template approval is not.** Create responses show a template ID with `status: PENDING`; read operations expose status such as APPROVED or REJECTED. There is no documented operation that makes a template approved. These are WhatsApp templates; the SMS DLT manager/template operations belong to a different service and approval process.

The recipient block/unblock API controls whether a WhatsApp user can message the business. It is not reseller-account suspension, disabling a Bulk9 customer, or disabling the WABA itself. Those account controls must be assessed from the separate reseller reference.

### Common request and response conventions

All 61 endpoint definitions require an `Authorization` header. Most call its value `YOUR_API_KEY` directly; a few descriptions say Access Token or Bearer Token/API Key. This category alone is inconsistent about whether a literal `Bearer ` prefix is appropriate; follow the reference's central authorization instructions and verify contract with Bulk9 before implementation.

Meta-shaped routes use `https://bulk9.com/dev/whatsapp/{version}/...`, with `version` defaulting to `v26.0`. This is a Bulk9-hosted proxy interface, even when its schema server description says Meta Graph API. WABA IDs, phone-number IDs, Meta template IDs, Bulk9 integer `message_id`, media IDs, upload handles, and outbound message IDs serve different roles and should not be substituted for one another.

Most Meta-shaped sends return `messaging_product`, `contacts[]` with `input`/`wa_id`, and `messages[]` with a `wamid` ID, frequently `message_status: accepted`. Accepted is not a delivery/read confirmation; reports/webhooks supply later status. The simple template route returns a Bulk9 `request_id`; the simple session schema documents only `status: success` and does not promise a message ID. Most pages define only HTTP 200, without endpoint-specific error responses, retry guidance, idempotency keys or rate limits.

### Account, number and business profile operations

[Get WABA & Template Details](https://docs.bulk9.com/reference/get-waba-template-details?domain=bulk9.com) is `GET /dev/dlt_manager/whatsapp`, with required query `type=number|template`. It provides the bridge between Bulk9's template `message_id`, Meta template IDs and each number/WABA. Its narrative includes number, verified/display-name status, quality rating, messaging tier, platform and connection status; template records add name, category, status, language, variable count and components. Despite `dlt_manager` in the URL, this page describes WhatsApp objects.

[Get Phone Numbers](https://docs.bulk9.com/reference/get-phone-numbers?domain=bulk9.com) lists a WABA's numbers, quality, verification state, throughput, onboarding timestamp and cursor data. The filtered variant uses the same path, required `fields`, and optional `filtering` whose example selects `account_mode=SANDBOX`. The example filtering string uses single quotes and is not valid JSON as written. No paging request parameters are documented despite returned cursors.

[Get Single Phone Number Details](https://docs.bulk9.com/reference/get-single-phone-number-details?domain=bulk9.com) uses a phone-number ID and required `fields` default selecting connection status, official-business flag, ID/name/verification/display number, platform, messaging limit and throughput. Display-name status is another GET view of that resource selecting `name_status`. WABA health status selects `health_status` on a WABA ID and returns whether sending is available, including per-entity state.

Two profile GET pages document the same resource with slightly different placeholder names. `get-whatsapp-business-profile` asks for `about,address,description,email,profile_picture_url,websites,vertical` and shows a business-profile response. The misspelled `get-buisness-profile` uses the same fields but its formal response schema incorrectly describes number/list fields (`id`, official-business flag, display number, verified name and paging). The narrative response still shows the business profile.

Both profile edit pages use `POST /dev/whatsapp/{version}/{phone_number_id}/whatsapp_business_profile`. General update accepts `messaging_product`, `address`, `description`, `vertical`, `about`, `email`, `websites[]`, `profile_picture_handle`; only `messaging_product` is marked required. The photo-focused view marks `messaging_product`, `vertical` and `profile_picture_handle` required, with vertical default `PROF_SERVICES`. Neither documents a structured success body. A profile-picture handle is a prior upload result, not an arbitrary remote image URL.

### Session messages

[Simple session send](https://docs.bulk9.com/reference/sendsessionmessage?domain=bulk9.com): `POST /dev/whatsapp-session`, required query `phone_number_id`, `to` (country code included), optional `udf1`, `udf2`, `udf3`. JSON body chooses one of eight types:

| Type | Required type-specific fields | Notes |
|---|---|---|
| text | `text` | Flat string body |
| image | `url` | Direct JPEG/PNG URL |
| document | `url`, `document_filename` | Filename is required here |
| audio | `url` | Direct audio URL |
| video | `url` | MP4/3GP named in description |
| location | `latitude`, `longitude`, `name`, `address` | Latitude/longitude declared strings |
| sticker | `url` | WebP named in description |
| reaction | `message_id`, `emoji` | Message ID is the WhatsApp `wamid` being reacted to |

Every variant requires `type`; each body variant also declares optional UDFs. The documentation does not settle precedence when the same UDF appears in query and body. UDF descriptions say values are returned in webhook notifications. There is no file-size ceiling or MIME whitelist beyond descriptions and no session-window explanation on this simple page.

[Meta-shaped session send](https://docs.bulk9.com/reference/sendmessage?domain=bulk9.com): `POST /dev/whatsapp/{version}/{phone_number_id}/messages`. The narrative explicitly limits session sends to **within 24 hours of the user's reply**. The base message requires `messaging_product`, `recipient_type`, `to` and `type`. It supports the same eight content types plus six interactive shapes and a read/typing shape:

- Text: nested `text.body` and `preview_url`.
- Image/video/document: nested media `link` or `id`; captions for image/video/document and `filename` for documents. Audio/sticker allow `link` or `id`.
- Location: numeric latitude/longitude plus name/address. Reaction: target message ID and emoji.
- Interactive list: text header/body/footer, action button, sections with rows (`id`, title, description).
- Interactive quick replies: action buttons with `reply.id` and `reply.title`; the description says **up to 3**, although the schema omits `maxItems`.
- Interactive catalog: full catalog button with optional retailer-ID thumbnail.
- Interactive single product: `catalog_id`, `product_retailer_id`.
- Interactive multiple products: catalog ID, sections with title and product retailer IDs, text header/body.
- Interactive CTA URL: text header/body/footer and action display text/URL.
- Read/typing: a separate payload requiring `messaging_product`, `status`, `message_id`, with optional `typing_indicator.type`; it is not a normal outbound message with a recipient and content type.

The request's nested schemas are weakly constrained: many practically necessary fields have no `required` declaration, media `link` versus `id` is not enforced as exactly one, and several interactive variants share the same type without a discriminator. Do not treat schema validity as proof the upstream message is usable.

### Template sends

[Simple template send](https://docs.bulk9.com/reference/sendwhatsappmessage?domain=bulk9.com) is the unusual **GET `/dev/whatsapp`** sending route. Required query: Bulk9 integer `message_id`, `phone_number_id`, `numbers`. Optional/conditional: pipe-separated `variables_values` when variables exist, `media_url` for a media header, `document_filename` for a custom PDF title. The docs call `numbers` a destination mobile number and provide no multi-recipient format or maximum; its plural name alone does not establish bulk-recipient support. Success is boolean `status`, message text, `request_id`.

All **13 advanced template-send pages** use the same **POST `/dev/whatsapp/{version}/{phone_number_id}/messages`**. Common JSON is `messaging_product=whatsapp`, recipient `to`, `type=template`, and `template.name`, `template.language.code`; most variants also send `recipient_type=individual` and `template.components`. Their distinct supported payloads were all read:

| Variant | Component and data requirements described |
|---|---|
| Authentication | Body text OTP and button at index 0; documentation says send the same OTP to both. Button `sub_type=url` is shown even for copy-code/one-tap; schema also lists `copy_code`. |
| Plain text | Template name and language; no parameters/media. |
| Media | Header image/video/document by link or media ID; document may have filename; optional text body variables. |
| Interactive | Header media, body text/currency/date-time (`fallback_value`, currency code and `amount_1000`), quick-reply payloads or URL button subtype and zero-based index. |
| Location | Location header with latitude/longitude/name/address, optional body text parameters. |
| Variables | Body text parameters filling positional template variables. |
| CTA URL | URL button with index and dynamic value. Narrative/example uses `type=payload`, `payload=value`; enum also allows `text` but no `text` field is declared. This conflicts with the URL/text parameter shape used by LTO and authentication examples. |
| Catalog | Body variables and `CATALOG` button action with `thumbnail_product_retailer_id`. |
| Multiple products | Header/body variables, `mpm` button action, thumbnail retailer ID, sections with product retailer IDs. |
| Carousel | Main BODY variables, CAROUSEL cards with `card_index`, card HEADER image link and BODY variables. This sending schema omits card button parameters and video despite the creation schema offering them. |
| Coupon code | Body variables and `COPY_CODE` button parameter `type=coupon_code`, `coupon_code`; example uses button index 1. |
| Limited-time offer | Image media ID, body variables, `limited_time_offer.expiration_time_ms` in Unix milliseconds, copy-code and dynamic URL buttons. The example timestamp is old sample data, not a current usable expiry. |
| Flows | Flow button action with optional `flow_token` (description says default `unused`) and arbitrary `flow_action_data`; opens an existing Flow. |

The pages use inconsistent component casing and button-index types (some strings, some integers); preserve the exact provider contract per variant and resolve ambiguity with Bulk9. Session interaction types and template component types are different payload structures even though they share the `/messages` route.

### Template management

All **13 creation pages** use **POST `/dev/whatsapp/{version}/{waba_id}/message_templates`** and create templates under an existing WABA. Creation JSON uses name, language, category, components. Response generally contains `id`, `status=PENDING`, category. Text/auth schemas explicitly require top-level fields; most rich-template schemas omit top-level required declarations despite examples clearly needing them.

| Creation variant | Fields and behavior described |
|---|---|
| Copy-code authentication | `category=authentication`, language default `en_US`; BODY `add_security_recommendation`, FOOTER `code_expiration_minutes`, BUTTONS with OTP/COPY_CODE and text. Narrative says all three components are required. |
| One-tap authentication | Body/footer/buttons strictly in that order; OTP `one_tap`, optional text/autofill text, required nonempty `supported_apps[]` with `package_name` and `signature_hash`; optional `message_send_ttl_seconds`. |
| Zero-tap authentication | Same structure as one-tap, OTP `zero_tap`; explicit `zero_tap_terms_accepted=true` required, supported apps required. |
| Text | BODY text and `example.body_text` nested arrays when variables occur; language defaults `en`; category enum MARKETING/UTILITY/AUTHENTICATION. |
| Media | HEADER format DOCUMENT/IMAGE/VIDEO with example `header_handle[]`; BODY text plus variable samples and optional FOOTER. Category MARKETING/UTILITY. |
| Location | HEADER format LOCATION needs no location sample at creation; body variable examples. Coordinates are supplied when sending. |
| Catalog | Body text/variables, footer, BUTTONS with CATALOG and label. |
| Multiple products | TEXT header and `header_text[]` sample, body variable examples, MPM button. Specific products/sections are chosen during sending. |
| Carousel | Main body; CAROUSEL cards each with HEADER IMAGE/VIDEO sample upload handles, BODY and BUTTONS. Button enum QUICK_REPLY/URL, but URL field absent in this page's button schema. |
| Limited-time offer | Header image/video sample, LTO text plus `has_expiration`, body variables, copy-code and URL buttons/examples. Schema category enum uppercase MARKETING/UTILITY conflicts with lowercase `marketing` in narrative and request example. |
| Coupon code | TEXT header, body variables, QUICK_REPLY and COPY_CODE button with sample coupon. The sample button coupon is `250FF`, while body/send sample uses `25OFF`; sample typo should not become business logic. |
| CTA | Body variables, URL buttons with static/dynamic URL and dynamic example. Enum also allows PHONE_NUMBER, but phone-number field is absent. |
| Flows | Body and FLOW button with existing `flow_id`, `navigate_screen`, `flow_action=navigate|data_exchange`. Does not create, upload, publish or manage the Flow itself. |

For the three authentication creation pages, `components` is constrained to min 1/max 3 with `anyOf` items, which does **not** enforce the required all-three component types, uniqueness or ordering stated in prose. One-tap and zero-tap examples do show all three. Copy-code uses uppercase component/button values, while one/zero-tap use lowercase; account for this documentation inconsistency.

[Edit Template](https://docs.bulk9.com/reference/edittemplate?domain=bulk9.com) uses POST `/dev/whatsapp/{version}/{template_id}`; body may contain name, language, category and header/body/footer/buttons. Prose says edits are usually limited to REJECTED/PAUSED templates or minor corrections, but gives no definitive eligibility/rate policy. Formal schema omits URL/phone/OTP-specific button fields despite listing those button types and omits media-header sample handle fields despite IMAGE/VIDEO/DOCUMENT format enums. Success is `success=true`.

Read operations list all templates under a WABA, query by required name on that same list resource, or fetch one by Meta template ID. Examples show name/components/language/status/category/ID and list cursors. The formal Get All schema contains only a `name` string and does not describe its example list response. By-ID and by-name schemas model component `format`/`text` as required for all components, which does not fit BODY/FOOTER/BUTTONS examples. Paging object-versus-array mismatches recur.

Both delete views use DELETE `/dev/whatsapp/{version}/{waba_id}/message_templates`. By-name explicitly requires query `name`. By-ID offers optional `hsm_id`, optional `name`, and prose says either or both; the schema does not require at least one. Both return `success=true`. There is no approve operation, approval bypass, built-in template editor interface, or template synchronization schedule documented here.

### Media, QR codes and recipient blocking

Media operations:

- GET `/dev/whatsapp/{version}/{phone_number_id}/media/{media_id}` returns media URL, MIME type, SHA256, file size, ID and messaging product from a received media ID. The category does not explain URL expiry, authenticated media download headers or retention.
- POST `/dev/whatsapp/{version}/{phone_number_id}/media_handle` requires multipart `file`, `messaging_product`, MIME `type`; returns upload handle `h` for relevant sample/resumable contexts.
- POST `/dev/whatsapp/{version}/{phone_number_id}/media` requires the same multipart fields; returns `id`, the media ID used for sending. Narrative calls it `media_id`, but actual response key is `id`.

The difference between an upload **handle** for template samples, a **media ID** for message media, and a direct media **URL** is important. There is no delete-media operation in this category, no maximum file sizes, and no comprehensive MIME/file-extension matrix. Descriptions mention MIME examples rather than enforce a supported-type enum.

QR code operations list/get/create/update/delete `/message_qrdls` under an existing phone-number ID. Creation JSON requires `prefilled_message` and `generate_qr_image=SVG|PNG`; response includes code, prefilled message, `wa.me/message/...` deep link and QR image URL. Update changes `prefilled_message`; delete returns success. Scanning opens a chat and pre-fills the user's input; it does not document sending the message automatically or linking a WhatsApp account. List/get use `{Version}` (capital V) while mutations use `{version}`; get uses `{your_qr_code_id}` while mutations use `{qr_code_id}`. These are placeholder-name inconsistencies, not different concrete resources.

Block operations use `/dev/whatsapp/{version}/{phone_number_id}/block_users`: GET lists blocked `wa_id` users and paging, POST JSON `messaging_product` plus `block_users:[{user: number}]` blocks, DELETE the same shape unblocks. Responses distinguish `added_users[]` and `removed_users[]` with input and normalized WhatsApp ID. The docs specify no batch ceiling. These controls operate on recipients who can contact a number, not business account status or reseller customer accounts.

### Older webhook settings, delivery reports and history

The [panel setup page](https://docs.bulk9.com/reference/set-whatsapp-webhook-panel?domain=bulk9.com) tells users to visit Dev API → API Webhook → WhatsApp Webhook and save a URL. It describes JSON POST notifications and shows `whatsapp_reports[]` mixing `incoming_message` and `status_update`. Incoming example has message ID, phone-number ID, sender, timestamp, message type, text body, and reply-context target; status example has request ID, phone-number ID, recipient, status, timestamp and errors.

Older API setting operations:

- GET `/dev/webhook/whatsapp/get`: saved URL and `webhook_status` in a data array; formal `return` field is declared string with default `true`.
- POST `/dev/webhook/whatsapp/set`: JSON `webhook_url`, `webhook_status=enable|disable`; response message confirms updated settings. Neither request body nor its fields are formally marked required.

This is the **older single-setting webhook interface**, separate from the newer Webhook (New) CRUD category reviewed elsewhere. The older pages do not explain migration between the two configurations, which takes precedence, fan-out, request signing, acknowledgement timeout, retry schedule, duplicate behavior or event filters. The legacy example is not enough to infer the full incoming-media/interactive-event contract.

GET `/dev/whatsapp/{REQUEST_ID}` manually retrieves reports for a send request. Example data has `type=status_update`, request ID, phone-number ID, recipient, `status=accepted`, nullable timestamp and errors. No retention limit is specified on this WhatsApp report-fetch page. Do not carry the separate SMS report retention limit over to WhatsApp by assumption. The examples alternate a Bulk9-looking request ID and a `wamid` under request-related names, without an explicit mapping contract across send formats; this requires care when correlating advanced sends to delivery reports.

GET `/dev/whatsapp_logs` requires `from` and `to` dates in YYYY-MM-DD. Prose says logs for **the last 3 days**. This is a short-history statement, not a promise that any arbitrary historic three-day span is available. No pagination or phone-number filter parameters appear on this page. Response lists status records and errors.

GET `/dev/whatsapp_summary` requires the same dates and says **a 30-day interval**. It reports sent/accepted/delivered/read/failed/rejected/pending counts. The docs do not specify whether these are current mutually exclusive status buckets, cumulative milestones, timezone boundaries or historical retention. The narrative example has `data` as an object; formal schema incorrectly declares an array. Counts must not be added/interpreted as conversion funnels without confirming their meaning.

### Documentation defects and implementation consequences

1. **Formal response types conflict with examples.** `success`/`return` are frequently strings in schemas although narrative examples use booleans; `is_official_business_account` is declared string but shown boolean. `throughput`, `paging`, nested `cursors`, WABA `health_status` and summary `data` are often arrays in schemas but objects in examples. Report timestamp/errors schemas are non-null strings although examples show null. Generated clients would mis-model real sample responses.
2. **Wrong copied schemas.** The misspelled business-profile GET describes number-list data in its formal response. Get All Templates formally describes only `name`; the actual example is a templated data list with paging. WABA/template-details response schema omits the `templates` records documented in its narrative.
3. **Required fields are under-specified.** Rich create payloads often mark none of their fields required, session nested fields are largely optional, authentication creation does not enforce all required components, and template-by-ID deletion permits no selector in schema. Provider validation must be confirmed before implementing form validation from these definitions.
4. **Button/media schemas are incomplete.** CTA send allows `type=text` without defining `text`; its payload example differs from other URL-button examples. Interactive send enumerates video/document parameter types without their corresponding objects. Carousel send omits buttons/video supplied by creation, carousel create URL buttons lack `url`, CTA create PHONE_NUMBER lacks a number property, and edit-template has only generic button label/type fields.
5. **Example data should not be copied literally.** Several narrative JSON strings contain Markdown link syntax (`[url](url)`) instead of a URL; OpenAPI examples often show cleaned raw URLs. Sample handles are old, one template example has a missing comma, template names include inconsistent case/spaces versus one-tap's lowercase/underscore guidance, coupon samples disagree, and LTO expiry samples are dated. These examples illustrate shape, not ready requests.
6. **Placeholder prose remains on many useful pages.** “This is your first endpoint” and “New Endpoint” coexist with real parameters/examples. Empty wrappers have no extra setup or lifecycle guidance. Do not infer missing capabilities from a section title.
7. **Limits are uneven.** Session 24-hour window, quick replies up to 3, authentication component count, app-list nonempty, three-day logs and 30-day summary interval are stated. Send throughput/bulk ceilings, media size caps, template review timing, most component/button length/count limits, log pagination and endpoint-specific failures are not.
8. **Onboarding and approval gaps are real documentation gaps.** Existing-account inspection, chat QR and recipient blocking should not be represented as signup, customer suspension or template approval capabilities. The reference alone cannot establish a complete account onboarding workflow.

### Exhaustive current page inventory

The following table gives the exact composed Bulk9-hosted method/path for each endpoint page. Duplicate method/path rows are intentional payload or field-selection views. `—` means a wrapper/panel page has no OpenAPI operation. All 73 pages are retrieved and read.

| # | Official page | Method | Exact path |
|---|---|---|---|
| 1 | [WABA Management](https://docs.bulk9.com/reference/waba-management?domain=bulk9.com) | — | Section wrapper |
| 2 | [Get WABA & Template Details](https://docs.bulk9.com/reference/get-waba-template-details?domain=bulk9.com) | GET | `/dev/dlt_manager/whatsapp` |
| 3 | [Get Phone Numbers](https://docs.bulk9.com/reference/get-phone-numbers?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{waba_id}/phone_numbers` |
| 4 | [Get Single Phone Number Details](https://docs.bulk9.com/reference/get-single-phone-number-details?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{phone_number_id}` |
| 5 | [Get Display Name Status](https://docs.bulk9.com/reference/get-display-name-status?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{phone-number_id}` |
| 6 | [Get Phone Numbers with Filtering](https://docs.bulk9.com/reference/get-phone-numbers-with-filtering?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{waba_id}/phone_numbers` |
| 7 | [Get WhatsApp Business Profile](https://docs.bulk9.com/reference/get-whatsapp-business-profile?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{phone-number_id}/whatsapp_business_profile` |
| 8 | [Get WABA Health Status](https://docs.bulk9.com/reference/get-waba-health-status?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{waba_id}` |
| 9 | [Get Buisness Profile](https://docs.bulk9.com/reference/get-buisness-profile?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{phone_number_id}/whatsapp_business_profile` |
| 10 | [Update Business Profile](https://docs.bulk9.com/reference/update-business-profile?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/whatsapp_business_profile` |
| 11 | [Update Business Profile Photo](https://docs.bulk9.com/reference/update-business-profile-photo?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/whatsapp_business_profile` |
| 12 | [Send Session Message](https://docs.bulk9.com/reference/send-session-message?domain=bulk9.com) | — | Section wrapper |
| 13 | [Send Session Message (Simple)](https://docs.bulk9.com/reference/sendsessionmessage?domain=bulk9.com) | POST | `/dev/whatsapp-session` |
| 14 | [META Format (Advanced)](https://docs.bulk9.com/reference/meta-format-advanced-1?domain=bulk9.com) | — | Section wrapper |
| 15 | [Send Session Message](https://docs.bulk9.com/reference/sendmessage?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 16 | [Send Template Message](https://docs.bulk9.com/reference/send-template-message?domain=bulk9.com) | — | Section wrapper |
| 17 | [Send Template Message (Simple)](https://docs.bulk9.com/reference/sendwhatsappmessage?domain=bulk9.com) | GET | `/dev/whatsapp` |
| 18 | [META Format (Advanced)](https://docs.bulk9.com/reference/meta-format-advanced?domain=bulk9.com) | — | Section wrapper |
| 19 | [Send Authentication Template](https://docs.bulk9.com/reference/sendauthenticationtemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 20 | [Send Text Template Message](https://docs.bulk9.com/reference/sendtexttemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 21 | [Send Media Template Message](https://docs.bulk9.com/reference/sendmediatemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 22 | [Send Interactive Template Message](https://docs.bulk9.com/reference/sendinteractivetemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 23 | [Send Location Template Message](https://docs.bulk9.com/reference/sendlocationtemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 24 | [Send Template (with variable)](https://docs.bulk9.com/reference/sendtemplatewithvariable?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 25 | [Send Template (CTA button)](https://docs.bulk9.com/reference/sendtemplatectabutton?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 26 | [Send Catalog Template Message](https://docs.bulk9.com/reference/sendcatalogtemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 27 | [Send Multi-Product Template Message](https://docs.bulk9.com/reference/sendmultiproducttemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 28 | [Send Carousel Template Message](https://docs.bulk9.com/reference/sendcarouseltemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 29 | [Send Coupon Code Template Message](https://docs.bulk9.com/reference/sendcouponcodetemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 30 | [Send Limited Time Offer Template Message](https://docs.bulk9.com/reference/sendlimitedtimeoffertemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 31 | [Send Flows Template Message](https://docs.bulk9.com/reference/sendflowstemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/messages` |
| 32 | [Template Management](https://docs.bulk9.com/reference/template-management?domain=bulk9.com) | — | Section wrapper |
| 33 | [Authentication](https://docs.bulk9.com/reference/authentication-1?domain=bulk9.com) | — | Section wrapper |
| 34 | [Create Copy Code Template](https://docs.bulk9.com/reference/createcopycodetemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 35 | [Create One-Tap Template](https://docs.bulk9.com/reference/createonetaptemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 36 | [Create Zero-Tap Template](https://docs.bulk9.com/reference/createzerotaptemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 37 | [Create Text Template](https://docs.bulk9.com/reference/createtexttemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 38 | [Create Media Template](https://docs.bulk9.com/reference/createmediatemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 39 | [Create Location Template](https://docs.bulk9.com/reference/createlocationtemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 40 | [Create Catalog Template](https://docs.bulk9.com/reference/createcatalogtemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 41 | [Create Multi-Product Template](https://docs.bulk9.com/reference/createmultiproducttemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 42 | [Create Carousel Template](https://docs.bulk9.com/reference/createcarouseltemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 43 | [Create Limited Time Offer Template](https://docs.bulk9.com/reference/createlimitedtimeoffertemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 44 | [Create Coupon Code Template](https://docs.bulk9.com/reference/createcouponcodetemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 45 | [Create Call To Action (CTA) Template](https://docs.bulk9.com/reference/createctatemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 46 | [Create Flows Template](https://docs.bulk9.com/reference/createflowstemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 47 | [Edit Template](https://docs.bulk9.com/reference/edittemplate?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{template_id}` |
| 48 | [Get All Templates](https://docs.bulk9.com/reference/get-all-templates?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 49 | [Get Template By ID](https://docs.bulk9.com/reference/get-template-by-id?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{template_id}` |
| 50 | [Get Template By Name](https://docs.bulk9.com/reference/get-template-by-name?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 51 | [Delete Template by ID](https://docs.bulk9.com/reference/deletetemplate?domain=bulk9.com) | DELETE | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 52 | [Delete Template by Name](https://docs.bulk9.com/reference/deletetemplatebyname?domain=bulk9.com) | DELETE | `/dev/whatsapp/{version}/{waba_id}/message_templates` |
| 53 | [Media Management](https://docs.bulk9.com/reference/media-management?domain=bulk9.com) | — | Section wrapper |
| 54 | [Get Media URL From Media ID (received in webhook)](https://docs.bulk9.com/reference/get-media-url-from-media-id?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{phone_number_id}/media/{media_id}` |
| 55 | [Create Media Handle](https://docs.bulk9.com/reference/createmediahandle?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/media_handle` |
| 56 | [Upload Media](https://docs.bulk9.com/reference/uploadmedia?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/media` |
| 57 | [List of QR Codes](https://docs.bulk9.com/reference/list-of-qr-codes?domain=bulk9.com) | GET | `/dev/whatsapp/{Version}/{phone_number_id}/message_qrdls` |
| 58 | [Get QR Code](https://docs.bulk9.com/reference/get-qr-code?domain=bulk9.com) | GET | `/dev/whatsapp/{Version}/{phone_number_id}/message_qrdls/{your_qr_code_id}` |
| 59 | [Create QR Code](https://docs.bulk9.com/reference/createqrcode?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/message_qrdls` |
| 60 | [Update QR Code](https://docs.bulk9.com/reference/updateqrcode?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/message_qrdls/{qr_code_id}` |
| 61 | [Delete QR Code](https://docs.bulk9.com/reference/deleteqrcode?domain=bulk9.com) | DELETE | `/dev/whatsapp/{version}/{phone_number_id}/message_qrdls/{qr_code_id}` |
| 62 | [Block Unblock WhatsApp User](https://docs.bulk9.com/reference/block-unblock-whatsapp-user?domain=bulk9.com) | — | Section wrapper |
| 63 | [Get Blocked Users](https://docs.bulk9.com/reference/get-blocked-users?domain=bulk9.com) | GET | `/dev/whatsapp/{version}/{phone_number_id}/block_users` |
| 64 | [Block User(s)](https://docs.bulk9.com/reference/block-users?domain=bulk9.com) | POST | `/dev/whatsapp/{version}/{phone_number_id}/block_users` |
| 65 | [Unblock User(s)](https://docs.bulk9.com/reference/unblockusers?domain=bulk9.com) | DELETE | `/dev/whatsapp/{version}/{phone_number_id}/block_users` |
| 66 | [WhatsApp Delivery Reports API](https://docs.bulk9.com/reference/whatsapp-delivery-reports-api?domain=bulk9.com) | — | Section wrapper |
| 67 | [Set WhatsApp Webhook (Panel)](https://docs.bulk9.com/reference/set-whatsapp-webhook-panel?domain=bulk9.com) | — | Panel setup and payload example |
| 68 | [Get WhatsApp Webhook URL](https://docs.bulk9.com/reference/get-whatsapp-webhook-url?domain=bulk9.com) | GET | `/dev/webhook/whatsapp/get` |
| 69 | [Set WhatsApp Webhook URL](https://docs.bulk9.com/reference/set-whatsapp-webhook-url?domain=bulk9.com) | POST | `/dev/webhook/whatsapp/set` |
| 70 | [Fetch Reports Manually](https://docs.bulk9.com/reference/fetch-reports-manually?domain=bulk9.com) | GET | `/dev/whatsapp/{REQUEST_ID}` |
| 71 | [WhatsApp Analytics](https://docs.bulk9.com/reference/whatsapp-analytics?domain=bulk9.com) | — | Section wrapper |
| 72 | [WhatsApp Logs](https://docs.bulk9.com/reference/whatsapp-logs?domain=bulk9.com) | GET | `/dev/whatsapp_logs` |
| 73 | [WhatsApp Logs Summary](https://docs.bulk9.com/reference/whatsapp-logs-summary?domain=bulk9.com) | GET | `/dev/whatsapp_summary` |

---

<a id="webhooks-review"></a>

## Bulk9 Webhook (New): complete current documentation review

Reviewed 2026-10-29 (Asia/Kolkata). Scope: all 20 pages in the official current **Webhook (New)** navigation: four overviews and 16 configuration operations. This is a public documentation review, with no account access, API execution, messaging, or configuration changes. Source snapshots are in `webhooks/`; every available embedded OpenAPI definition and every JSON example was parsed. Nothing in this assigned category was left unread.

The four overview pages report `updatedAt: 2026-08-20T07:27:17.000Z`; all 16 operation pages report `2026-07-29T05:07:14.000Z`. These are documentation metadata, not proof of API release dates. Sources were retrieved as `https://docs.bulk9.com/reference/<slug>.md?domain=bulk9.com`. Canonical human links are below.

### Main findings

Bulk9 documents configurable callbacks for SMS, OTP, WhatsApp, and RCS. SMS/OTP support delivery updates; WhatsApp/RCS also support incoming customer messages. There are service-specific filters, optional identity scoping, custom payload templates, preset CleverTap formats, and a WhatsApp Meta-shaped format. This is enough to understand the intended design, but several details needed for a production integration remain unspecified.

1. **Callback authentication has a documented static-header option.** Create/update schemas accept `headers`, an object of outgoing callback headers, including a sample `Authorization` value. The API key in the management request's `Authorization` header is a separate credential. No dynamic signing, HMAC algorithm, `X-Hub-Signature-256`, timestamp authentication, replay prevention, verification challenge, source-IP list, or key-rotation procedure is specified in these 20 pages. This is a missing contract, not proof that the platform lacks those capabilities. [Create WhatsApp Webhook](https://docs.bulk9.com/reference/create-whatsapp-webhook?domain=bulk9.com)
2. **`meta_direct` describes the body format, not a guarantee of an untouched Meta request.** The overview says the payload mimics Meta's Cloud API structure. Optional media handling downloads media with system credentials, hosts it on CDN/S3, and inserts a publicly accessible URL. Do not infer preservation of Meta's signature or exact original bytes from that format name. The overview mentions enabling injection but the create/update schema provides no field to do so. [WhatsApp Webhook Overview](https://docs.bulk9.com/reference/whatsapp-webhook?domain=bulk9.com)
3. **No configuration operation has a response schema or body example.** All 16 document only HTTP 200 with a brief success description. Even listing has no shape for webhook IDs, field values, pagination, or deleted entries. None defines validation/authentication/not-found errors, limits errors, or partial-failure behavior. Exact response parsing cannot be implemented from these pages alone. [List SMS Webhooks](https://docs.bulk9.com/reference/list-sms-webhooks?domain=bulk9.com), [List OTP Webhooks](https://docs.bulk9.com/reference/list-otp-webhooks?domain=bulk9.com), [List WhatsApp Webhooks](https://docs.bulk9.com/reference/list-whatsapp-webhooks?domain=bulk9.com), [List RCS Webhooks](https://docs.bulk9.com/reference/list-rcs-webhooks?domain=bulk9.com)
4. **Reliability is underspecified.** Overview variables include `post_attempt`, described as callback retry count. No attempt limit, schedule, backoff, acknowledgment status, timeout, ordering, duplicate-delivery guarantee, dead-letter handling, retry-log query, or replay endpoint is described in this category. `delivery_attempt`/`dlr_attempt` refer to message delivery and must not be treated as webhook retry count. [SMS Webhook Overview](https://docs.bulk9.com/reference/sms-webhook?domain=bulk9.com)
5. **Limits/deletion need clarification.** Each create page states a maximum of 10 webhooks in its service context. Whether that cap is per account, service, or identity, whether disabled/soft-deleted rows consume it, and whether deletion cancels queued retries are not specified. Deletion is explicitly soft deletion; no restore or permanent-delete operation is documented. [Create SMS](https://docs.bulk9.com/reference/create-sms-webhook?domain=bulk9.com), [Create OTP](https://docs.bulk9.com/reference/create-otp-webhook?domain=bulk9.com), [Create WhatsApp](https://docs.bulk9.com/reference/create-whatsapp-webhook?domain=bulk9.com), [Create RCS](https://docs.bulk9.com/reference/create-rcs-webhook?domain=bulk9.com), [Delete WhatsApp](https://docs.bulk9.com/reference/delete-whatsapp-webhook?domain=bulk9.com)

### Complete page and operation inventory

Management base URL is **`https://bulk9.com`**, not the documentation host. Every operation requires `Authorization: YOUR_API_KEY` as a plain header value; these schemas do not add `Bearer`. PUT/DELETE additionally require a string path `id`. The list endpoints show no query parameters. Each row below was read in full.

| Page | Operation/path | Documented result |
|---|---|---|
| [SMS Webhook Overview](https://docs.bulk9.com/reference/sms-webhook?domain=bulk9.com) | Narrative | Formats, UI mapping, 28 variables, two callback examples |
| [List SMS Webhooks](https://docs.bulk9.com/reference/list-sms-webhooks?domain=bulk9.com) | `GET /dev/webhook/v2/sms` | 200, list retrieved |
| [Create SMS Webhook](https://docs.bulk9.com/reference/create-sms-webhook?domain=bulk9.com) | `POST /dev/webhook/v2/sms` | 200, configuration saved |
| [Update SMS Webhook](https://docs.bulk9.com/reference/update-sms-webhook?domain=bulk9.com) | `PUT /dev/webhook/v2/sms/{id}` | 200, configuration updated |
| [Delete SMS Webhook](https://docs.bulk9.com/reference/delete-sms-webhook?domain=bulk9.com) | `DELETE /dev/webhook/v2/sms/{id}` | 200, soft deleted |
| [OTP Webhook Overview](https://docs.bulk9.com/reference/otp-webhook?domain=bulk9.com) | Narrative | Formats, UI mapping, 33 variables, two callback examples |
| [List OTP Webhooks](https://docs.bulk9.com/reference/list-otp-webhooks?domain=bulk9.com) | `GET /dev/webhook/v2/otp` | 200, list retrieved |
| [Create OTP Webhook](https://docs.bulk9.com/reference/create-otp-webhook?domain=bulk9.com) | `POST /dev/webhook/v2/otp` | 200, configuration saved |
| [Update OTP Webhook](https://docs.bulk9.com/reference/update-otp-webhook?domain=bulk9.com) | `PUT /dev/webhook/v2/otp/{id}` | 200, configuration updated |
| [Delete OTP Webhook](https://docs.bulk9.com/reference/delete-otp-webhook?domain=bulk9.com) | `DELETE /dev/webhook/v2/otp/{id}` | 200, soft deleted |
| [WhatsApp Webhook Overview](https://docs.bulk9.com/reference/whatsapp-webhook?domain=bulk9.com) | Narrative | Three formats, UI mapping, 31 variables, six callback examples |
| [List WhatsApp Webhooks](https://docs.bulk9.com/reference/list-whatsapp-webhooks?domain=bulk9.com) | `GET /dev/webhook/v2/whatsapp` | 200, list retrieved |
| [Create WhatsApp Webhook](https://docs.bulk9.com/reference/create-whatsapp-webhook?domain=bulk9.com) | `POST /dev/webhook/v2/whatsapp` | 200, configuration saved |
| [Update WhatsApp Webhook](https://docs.bulk9.com/reference/update-whatsapp-webhook?domain=bulk9.com) | `PUT /dev/webhook/v2/whatsapp/{id}` | 200, configuration updated |
| [Delete WhatsApp Webhook](https://docs.bulk9.com/reference/delete-whatsapp-webhook?domain=bulk9.com) | `DELETE /dev/webhook/v2/whatsapp/{id}` | 200, soft deleted |
| [RCS Webhook Overview](https://docs.bulk9.com/reference/rcs-webhook?domain=bulk9.com) | Narrative | Formats, UI mapping, 30 variables, two callback examples |
| [List RCS Webhooks](https://docs.bulk9.com/reference/list-rcs-webhooks?domain=bulk9.com) | `GET /dev/webhook/v2/rcs` | 200, list retrieved |
| [Create RCS Webhook](https://docs.bulk9.com/reference/create-rcs-webhook?domain=bulk9.com) | `POST /dev/webhook/v2/rcs` | 200, configuration saved |
| [Update RCS Webhook](https://docs.bulk9.com/reference/update-rcs-webhook?domain=bulk9.com) | `PUT /dev/webhook/v2/rcs/{id}` | 200, configuration updated |
| [Delete RCS Webhook](https://docs.bulk9.com/reference/delete-rcs-webhook?domain=bulk9.com) | `DELETE /dev/webhook/v2/rcs/{id}` | 200, soft deleted |

Operation IDs follow `{get|post|put|delete}_dev_webhook_v2_{sms|otp|whatsapp|rcs}`. OpenAPI documents are version 3.0.0, titled Developer Webhooks (New) API, API version 1.0.0. Create/update schema names are `SmsWebhookConfig`, `OtpWebhookConfig`, `WhatsAppWebhookConfig`, and `RcsWebhookConfig`. For each service the POST and PUT component schemas are identical; PUT is not documented as a partial update.

### Configuration contract, including less-visible fields

All POST/PUT bodies use `application/json`. The request body itself has no explicit OpenAPI `required: true`, but the referenced object marks the following nine properties required: `name`, `url`, `method`, `content_type`, `status`, `event`, `payload_type`, `template`, `payload_transform`. A default value in a property does not remove this required marker. Optional properties are `payload`, `headers`, and (except OTP) `identity_id`. [Update SMS](https://docs.bulk9.com/reference/update-sms-webhook?domain=bulk9.com), [Update OTP](https://docs.bulk9.com/reference/update-otp-webhook?domain=bulk9.com), [Update WhatsApp](https://docs.bulk9.com/reference/update-whatsapp-webhook?domain=bulk9.com), [Update RCS](https://docs.bulk9.com/reference/update-rcs-webhook?domain=bulk9.com)

| Property | Type / allowed values | Default and significance |
|---|---|---|
| `name` | String | Friendly internal label; no length or uniqueness rules |
| `url` | String | Destination; example uses HTTPS, but no URI format or scheme restriction is specified |
| `method` | `POST`, `GET`, `PUT` | `POST`; this is the delivery method, independent of management API HTTP method |
| `content_type` | `application/json`, `application/x-www-form-urlencoded`, `application/xml` | `application/json`; this is callback encoding, not management request encoding |
| `payload_transform` | `standard`, `raw_json` | `standard`; shown in UI only for form encoding, yet required in all object schemas |
| `status` | `active`, `inactive` | `active`; on/off for triggers |
| `payload_type` | `SIMPLIFIED`, `RAW` | `SIMPLIFIED`; described only as a formatting level, with no operational comparison |
| `payload` | String | JSON/XML template text; not a JSON object; interpolation uses `@{{request_id}}`, `@{{status}}`, and other listed variables |
| `headers` | Object | Custom callback headers; arbitrary key/value shapes are not further constrained |
| `template` | Service-specific string enum | `custom`; presets lock event/method/content-type/body in the UI |
| `event` | Service-specific string enum | `all`; a single string filter, no array/list format |
| `identity_id` | Optional string; absent for OTP | Narrative says default `all`; SMS entity ID, WhatsApp phone-number ID, or RCS bot ID |

The UI overviews also show a `service` selector, but the create/update schema contains no `service` body property: the management URL selects the service. Conversely, `headers` and `payload_type` exist in the schema but do not appear in overview UI mapping tables. No JSON-escaping rules for substituted customer text, typed interpolation rules, XML escaping, missing-variable behavior, payload size limit, nested macro expressions, or GET query construction example are provided.

| Service | `template` enum | `event` enum | `identity_id` |
|---|---|---|---|
| SMS | `custom`, `clevertap` | `all`, `delivered`, `failed` | Entity ID |
| OTP | `custom`, `clevertap` | `all`, `delivered`, `failed` | No property; UI explicitly hides it |
| WhatsApp | `custom`, `clevertap_whatsapp`, `meta_direct` | `all`, `sent`, `delivered`, `read`, `failed`, `received` | Phone-number ID |
| RCS | `custom`, `clevertap_rcs` | `all`, `sent`, `delivered`, `read`, `failed`, `received` | Bot ID |

Preset locking is descriptive; no OpenAPI conditional schema explains which required fields should be omitted, accepted, ignored, or forced for presets. `payload_type=RAW`, `payload_transform=raw_json`, and `template=meta_direct` are three different settings; the docs do not say they are interchangeable.

### Callback fields and examples by service

#### Common fields

All four standard formats list `request_id`, `server_request_id` (alias), `route`, `sender_id`, `delivery_attempt`, `dlr_attempt` (alias), `character_count`, `mobile`, `status`, `status_lower`, `status_upper`, `status_title`, `status_description`, `udf1`, `udf2`, `udf3`, `post_attempt`, and `webhook_type`. IDs, routes, phone values, statuses, UDFs, and event type are strings; character and attempt counts are integers. UDFs are described as values supplied in send requests and returned for correlation. The overviews list variables available for templates; they do not establish that every variable is present in every actual event.

The general `status` descriptions use lower-case examples while all standard delivered examples use `"Delivered"`. Explicit case-specific fields exist, so avoid treating `status` capitalization as a stable enum. `webhook_type` examples distinguish `status_update` and, for WhatsApp/RCS, `incoming_message`. These are example values, not formal exhaustive enum schemas.

#### SMS

SMS adds `server_id` (integer), `sms_language`, `sms_count` (integer), `amount_debited` (string), `sent_timestamp`/`delivery_timestamp` (integer Unix times), `sent_time`/`delivery_time` (formatted strings), `failure_reason`, and `description`. The overview illustrates routes `dlt`/`dlt_manual`, and describes `mobile` as a 10-digit recipient. It supplies one complete standard delivered object and one CleverTap delivery object. [SMS overview](https://docs.bulk9.com/reference/sms-webhook?domain=bulk9.com)

The standard example's Unix timestamp `1718712000` corresponds to 2024-06-18 12:00:00 UTC while its adjacent string says `2026-06-18 12:00:00`. This is a two-year sample inconsistency, not a reliable time conversion example. Its successful delivery object also puts success text in `failure_reason`, so that field's presence/nonemptiness alone does not identify failure.

#### OTP

OTP includes every SMS variable, plus `channel`, `type`, `phone_number_id`, `recipient_id`, `category`. `channel` examples are `sms`/`whatsapp`/`rcs`; type examples are `template`/`sms`; category example is `AUTHENTICATION`. The standard example is SMS channel with blank phone-number ID. This documents cross-channel metadata, but does not itself document channel-selection/fallback behavior or prove any OTP send endpoint accepts every channel. OTP verification success/expiry are not among the subscription event enum values. The same timestamp/sample failure-reason inconsistencies occur here. CleverTap is called **CleverTap (SMS)** even in the OTP category. [OTP overview](https://docs.bulk9.com/reference/otp-webhook?domain=bulk9.com)

#### WhatsApp

WhatsApp adds `phone_number_id`, `display_phone_number`, `waba_id`, `recipient_id`, `category`, `mime_type`, `media_url`, `caption`, `from`, `message_type`, `body`, `context_message_id`, and `reply_to_message_id` (alias of context message ID). Its standard incoming example is a button reply: text `Approve` and outbound `wamid` in the two context fields. That is useful reply correlation, but the documented simplified incoming object does not contain a dedicated incoming message-ID/timestamp field. The list does not include delivery timestamps or a structured Meta errors array either. This limits a deduplication/ordering strategy based exclusively on these documented simplified fields. [WhatsApp overview](https://docs.bulk9.com/reference/whatsapp-webhook?domain=bulk9.com)

Six examples were reviewed: standard status; standard incoming button; CleverTap status; META DIRECT status; META DIRECT incoming text; META DIRECT incoming image with injected media URL. Meta-shaped examples use `object`, `entry[]`, `changes[]`, `value`, `metadata`, and status/message arrays. Text/image incoming examples carry `messages[].id`, `timestamp`, `from`, plus contact profile/`wa_id`; their presence is clearer than in the simplified incoming example. The status example uses a Bulk9-style `W...` identifier in `statuses[].id`; it should not be assumed identical to an outbound `wamid`. The example `entry[].id` equals its phone-number ID even though the overall object is a business-account object; actual identifier mapping needs confirmation.

Media injection is specifically described as asynchronous downloading of incoming `image`, `document`, `video`, or `audio` with platform credentials, rehosting, and insertion of `media_url` inside the media object. The example also retains the Meta media ID, SHA-256 string, MIME type, and caption. No toggle name, default, upload delay, callback coordination, failure fallback, file limit, expiry, retention, access policy beyond public accessibility, deletion API, or regional storage guarantee is specified. Do not assume `media_url` exists for every incoming message or permanently remains valid.

#### RCS

RCS adds `bot_id`, `error_message`, `from`, `message_type`, `body`, `ts` (string Unix reference), `failure_reason`, `description`, `mime_type`, `media_url`, `caption`, and `timestamp` (integer event time). It supplies a standard delivered example and CleverTap delivered example, but no incoming-message example despite advertising that capability and exposing the `received` event. The delivered sample contains `error_message: "Test error message"`; interpret overall status rather than that field's nonemptiness alone. This category documents RCS callbacks/configuration, not RCS sending APIs. [RCS overview](https://docs.bulk9.com/reference/rcs-webhook?domain=bulk9.com)

#### CleverTap across all services

Each CleverTap example has the same broad structure: `payloadVersion` string `"1"`, `statuses` array, and per-item `msgId`, lowercase `status`, string Unix `timestamp`, `description`. Example IDs are service-prefixed S/O/W/R. There is no incoming-message CleverTap example or formal callback response schema. No account credentials, CleverTap endpoint rules, authentication requirements, or precise locked transport defaults are explained in these pages.

### Issues to resolve before implementation

- Confirm the actual list/create/update/delete response bodies, ID source, and errors; confirm API key scheme against the main Authorization page.
- Confirm whether the 10-webhook cap is per service/account/identity, and behavior of inactive/deleted records and duplicate matching subscriptions.
- Confirm callback success status/timeout, retries/backoff, ordering, duplication, retention, inspection logs, replay, and whether one failure affects other subscribers.
- Confirm preset override behavior and required/default fields, `RAW` versus `SIMPLIFIED`, form `raw_json`, GET query encoding, XML serialization, and escaping of user-controlled text.
- Confirm callback authentication/static custom-header behavior for every preset and any supported signing scheme. Never assume a forwarded Meta-shaped payload is signed with the application's Meta secret.
- Confirm media injection enablement, retention and public-access implications, error handling, and message identifier mapping.
- Confirm simplified inbound event ID/timestamp support, tenant/phone identity scoping, complete inbound message types, and RCS incoming examples.
- Confirm how the new multi-webhook API coexists with the older single WhatsApp webhook settings. These 20 pages do not define migration, precedence, or duplicate-delivery behavior between them.

These are documentation gaps and design questions. They are not claims of observed runtime defects or blockers that have been tested against the live API.

### Review evidence

- `webhooks/inventory.json`: 20 fetched page URLs and byte counts.
- `webhooks/read-audit.json`: every page marked read, metadata, JSON-block count, parsing status.
- `webhooks/*.md`: complete official source pages including full inline OpenAPI.
- `webhooks/*.openapi.json`: 16 extracted complete OpenAPI definitions.
- `webhooks/*.payload-examples.json`: all 12 callback example bodies from four overviews.

No credentials were obtained or used. Literal credential-like strings in downloaded schemas are official sample placeholders only. No repository source was modified.

---

<a id="page-inventory"></a>

## Complete public-reference page inventory

Fetched and reviewed 29 October 2026. All 118 pages have full source snapshots; 96 contain OpenAPI operations. Paths below include the server base path. Duplicate template variants are not separate API functions.

| Category | Page | Documented method/path |
|---|---|---|
| Authorization | [Authorization](https://docs.bulk9.com/reference/authorization?domain=bulk9.com) | Narrative/wrapper |
| SMS API | [DLT SMS](https://docs.bulk9.com/reference/dlt-sms?domain=bulk9.com) | `GET /dev/bulkV2` |
| SMS API | [DLT SMS (Single)](https://docs.bulk9.com/reference/dlt-sms-single?domain=bulk9.com) | `POST /dev/bulkV2` |
| SMS API | [DLT SMS (Multiple)](https://docs.bulk9.com/reference/dlt-sms-multiple?domain=bulk9.com) | `POST /dev/custom` |
| SMS API | [DLT SMS (Manual) API](https://docs.bulk9.com/reference/dlt-manual-api?domain=bulk9.com) | Narrative/wrapper |
| SMS API | [DLT Manual](https://docs.bulk9.com/reference/dlt-manual?domain=bulk9.com) | `GET /dev/bulkV2` |
| SMS API | [DLT Manual (Single)](https://docs.bulk9.com/reference/dlt-manual-single?domain=bulk9.com) | `POST /dev/bulkV2` |
| SMS API | [DLT Manual (Multiple)](https://docs.bulk9.com/reference/dlt-manual-multiple?domain=bulk9.com) | `POST /dev/custom` |
| SMS API | [DLT Manager API](https://docs.bulk9.com/reference/dlt-manager?domain=bulk9.com) | Narrative/wrapper |
| SMS API | [View Sender/Template](https://docs.bulk9.com/reference/view-sender-1?domain=bulk9.com) | `GET /dev/dlt_manager` |
| SMS API | [Add Entity](https://docs.bulk9.com/reference/add-entity?domain=bulk9.com) | `POST /dev/dlt_manager/add_entity` |
| SMS API | [Add Sender ID](https://docs.bulk9.com/reference/add-sender-id?domain=bulk9.com) | `POST /dev/dlt_manager/add_sender` |
| SMS API | [Add Sender ID (Excel)](https://docs.bulk9.com/reference/add-sender-id-excel?domain=bulk9.com) | `POST /dev/dlt_manager/add_sender_excel` |
| SMS API | [Add Conten Templates](https://docs.bulk9.com/reference/add-conten-template?domain=bulk9.com) | `POST /dev/dlt_manager/add_template` |
| SMS API | [Add Content Templates (Excel)](https://docs.bulk9.com/reference/add-content-templates-excel?domain=bulk9.com) | `POST /dev/dlt_manager/add_template_excel` |
| SMS API | [SMS Delivery Report API](https://docs.bulk9.com/reference/delivery-fetch-api?domain=bulk9.com) | Narrative/wrapper |
| SMS API | [Fetch Reports Manually](https://docs.bulk9.com/reference/fetch-delivery-reports?domain=bulk9.com) | `GET /dev/dlr/{request_id}` |
| SMS API | [SMS Analytics](https://docs.bulk9.com/reference/sms-analytics?domain=bulk9.com) | Narrative/wrapper |
| SMS API | [SMS Logs](https://docs.bulk9.com/reference/sms-analytics-api?domain=bulk9.com) | `GET /dev/sms_logs` |
| SMS API | [SMS Logs Summary](https://docs.bulk9.com/reference/sms-logs-summary?domain=bulk9.com) | `GET /dev/sms_summary` |
| OTP API | [Send OTP](https://docs.bulk9.com/reference/send-otp?domain=bulk9.com) | `POST /dev/otp/send` |
| OTP API | [Verify OTP](https://docs.bulk9.com/reference/verify-otp?domain=bulk9.com) | `POST /dev/otp/verify` |
| OTP API | [Resend OTP](https://docs.bulk9.com/reference/resend-otp?domain=bulk9.com) | `POST /dev/otp/resend` |
| WhatsApp API | [WABA Management](https://docs.bulk9.com/reference/waba-management?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Get WABA & Template Details](https://docs.bulk9.com/reference/get-waba-template-details?domain=bulk9.com) | `GET /dev/dlt_manager/whatsapp` |
| WhatsApp API | [Get Phone Numbers](https://docs.bulk9.com/reference/get-phone-numbers?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{waba_id}/phone_numbers` |
| WhatsApp API | [Get Single Phone Number Details](https://docs.bulk9.com/reference/get-single-phone-number-details?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{phone_number_id}` |
| WhatsApp API | [Get Display Name Status](https://docs.bulk9.com/reference/get-display-name-status?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{phone-number_id}` |
| WhatsApp API | [Get Phone Numbers with Filtering](https://docs.bulk9.com/reference/get-phone-numbers-with-filtering?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{waba_id}/phone_numbers` |
| WhatsApp API | [Get WhatsApp Business Profile](https://docs.bulk9.com/reference/get-whatsapp-business-profile?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{phone-number_id}/whatsapp_business_profile` |
| WhatsApp API | [Get WABA Health Status](https://docs.bulk9.com/reference/get-waba-health-status?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{waba_id}` |
| WhatsApp API | [Get Buisness Profile](https://docs.bulk9.com/reference/get-buisness-profile?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{phone_number_id}/whatsapp_business_profile` |
| WhatsApp API | [Update Business Profile](https://docs.bulk9.com/reference/update-business-profile?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/whatsapp_business_profile` |
| WhatsApp API | [Update Business Profile Photo](https://docs.bulk9.com/reference/update-business-profile-photo?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/whatsapp_business_profile` |
| WhatsApp API | [Send Session Message](https://docs.bulk9.com/reference/send-session-message?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Send Session Message (Simple)](https://docs.bulk9.com/reference/sendsessionmessage?domain=bulk9.com) | `POST /dev/whatsapp-session` |
| WhatsApp API | [META Format (Advanced)](https://docs.bulk9.com/reference/meta-format-advanced-1?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Send Session Message](https://docs.bulk9.com/reference/sendmessage?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Template Message](https://docs.bulk9.com/reference/send-template-message?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Send Template Message (Simple)](https://docs.bulk9.com/reference/sendwhatsappmessage?domain=bulk9.com) | `GET /dev/whatsapp` |
| WhatsApp API | [META Format (Advanced)](https://docs.bulk9.com/reference/meta-format-advanced?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Send Authentication Template](https://docs.bulk9.com/reference/sendauthenticationtemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Text Template Message](https://docs.bulk9.com/reference/sendtexttemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Media Template Message](https://docs.bulk9.com/reference/sendmediatemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Interactive Template Message](https://docs.bulk9.com/reference/sendinteractivetemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Location Template Message](https://docs.bulk9.com/reference/sendlocationtemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Template (with variable)](https://docs.bulk9.com/reference/sendtemplatewithvariable?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Template (CTA button)](https://docs.bulk9.com/reference/sendtemplatectabutton?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Catalog Template Message](https://docs.bulk9.com/reference/sendcatalogtemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Multi-Product Template Message](https://docs.bulk9.com/reference/sendmultiproducttemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Carousel Template Message](https://docs.bulk9.com/reference/sendcarouseltemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Coupon Code Template Message](https://docs.bulk9.com/reference/sendcouponcodetemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Limited Time Offer Template Message](https://docs.bulk9.com/reference/sendlimitedtimeoffertemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Send Flows Template Message](https://docs.bulk9.com/reference/sendflowstemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/messages` |
| WhatsApp API | [Template Management](https://docs.bulk9.com/reference/template-management?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Authentication](https://docs.bulk9.com/reference/authentication-1?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Create Copy Code Template](https://docs.bulk9.com/reference/createcopycodetemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create One-Tap Template](https://docs.bulk9.com/reference/createonetaptemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Zero-Tap Template](https://docs.bulk9.com/reference/createzerotaptemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Text Template](https://docs.bulk9.com/reference/createtexttemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Media Template](https://docs.bulk9.com/reference/createmediatemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Location Template](https://docs.bulk9.com/reference/createlocationtemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Catalog Template](https://docs.bulk9.com/reference/createcatalogtemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Multi-Product Template](https://docs.bulk9.com/reference/createmultiproducttemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Carousel Template](https://docs.bulk9.com/reference/createcarouseltemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Limited Time Offer Template](https://docs.bulk9.com/reference/createlimitedtimeoffertemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Coupon Code Template](https://docs.bulk9.com/reference/createcouponcodetemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Call To Action (CTA) Template](https://docs.bulk9.com/reference/createctatemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Create Flows Template](https://docs.bulk9.com/reference/createflowstemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Edit Template](https://docs.bulk9.com/reference/edittemplate?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{template_id}` |
| WhatsApp API | [Get All Templates](https://docs.bulk9.com/reference/get-all-templates?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Get Template By ID](https://docs.bulk9.com/reference/get-template-by-id?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{template_id}` |
| WhatsApp API | [Get Template By Name](https://docs.bulk9.com/reference/get-template-by-name?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Delete Template by ID](https://docs.bulk9.com/reference/deletetemplate?domain=bulk9.com) | `DELETE /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Delete Template by Name](https://docs.bulk9.com/reference/deletetemplatebyname?domain=bulk9.com) | `DELETE /dev/whatsapp/{version}/{waba_id}/message_templates` |
| WhatsApp API | [Media Management](https://docs.bulk9.com/reference/media-management?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Get Media URL From Media ID (received in webhook)](https://docs.bulk9.com/reference/get-media-url-from-media-id?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{phone_number_id}/media/{media_id}` |
| WhatsApp API | [Create Media Handle](https://docs.bulk9.com/reference/createmediahandle?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/media_handle` |
| WhatsApp API | [Upload Media](https://docs.bulk9.com/reference/uploadmedia?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/media` |
| WhatsApp API | [List of QR Codes](https://docs.bulk9.com/reference/list-of-qr-codes?domain=bulk9.com) | `GET /dev/whatsapp/{Version}/{phone_number_id}/message_qrdls` |
| WhatsApp API | [Get QR Code](https://docs.bulk9.com/reference/get-qr-code?domain=bulk9.com) | `GET /dev/whatsapp/{Version}/{phone_number_id}/message_qrdls/{your_qr_code_id}` |
| WhatsApp API | [Create QR Code](https://docs.bulk9.com/reference/createqrcode?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/message_qrdls` |
| WhatsApp API | [Update QR Code](https://docs.bulk9.com/reference/updateqrcode?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/message_qrdls/{qr_code_id}` |
| WhatsApp API | [Delete QR Code](https://docs.bulk9.com/reference/deleteqrcode?domain=bulk9.com) | `DELETE /dev/whatsapp/{version}/{phone_number_id}/message_qrdls/{qr_code_id}` |
| WhatsApp API | [Block Unblock WhatsApp User](https://docs.bulk9.com/reference/block-unblock-whatsapp-user?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Get Blocked Users](https://docs.bulk9.com/reference/get-blocked-users?domain=bulk9.com) | `GET /dev/whatsapp/{version}/{phone_number_id}/block_users` |
| WhatsApp API | [Block User(s)](https://docs.bulk9.com/reference/block-users?domain=bulk9.com) | `POST /dev/whatsapp/{version}/{phone_number_id}/block_users` |
| WhatsApp API | [Unblock User(s)](https://docs.bulk9.com/reference/unblockusers?domain=bulk9.com) | `DELETE /dev/whatsapp/{version}/{phone_number_id}/block_users` |
| WhatsApp API | [WhatsApp Delivery Reports API](https://docs.bulk9.com/reference/whatsapp-delivery-reports-api?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Set WhatsApp Webhook (Panel)](https://docs.bulk9.com/reference/set-whatsapp-webhook-panel?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [Get WhatsApp Webhook URL](https://docs.bulk9.com/reference/get-whatsapp-webhook-url?domain=bulk9.com) | `GET /dev/webhook/whatsapp/get` |
| WhatsApp API | [Set WhatsApp Webhook URL](https://docs.bulk9.com/reference/set-whatsapp-webhook-url?domain=bulk9.com) | `POST /dev/webhook/whatsapp/set` |
| WhatsApp API | [Fetch Reports Manually](https://docs.bulk9.com/reference/fetch-reports-manually?domain=bulk9.com) | `GET /dev/whatsapp/{REQUEST_ID}` |
| WhatsApp API | [WhatsApp Analytics](https://docs.bulk9.com/reference/whatsapp-analytics?domain=bulk9.com) | Narrative/wrapper |
| WhatsApp API | [WhatsApp Logs](https://docs.bulk9.com/reference/whatsapp-logs?domain=bulk9.com) | `GET /dev/whatsapp_logs` |
| WhatsApp API | [WhatsApp Logs Summary](https://docs.bulk9.com/reference/whatsapp-logs-summary?domain=bulk9.com) | `GET /dev/whatsapp_summary` |
| Webhook (New) | [SMS Webhook Overview](https://docs.bulk9.com/reference/sms-webhook?domain=bulk9.com) | Narrative/wrapper |
| Webhook (New) | [List SMS Webhooks](https://docs.bulk9.com/reference/list-sms-webhooks?domain=bulk9.com) | `GET /dev/webhook/v2/sms` |
| Webhook (New) | [Create SMS Webhook](https://docs.bulk9.com/reference/create-sms-webhook?domain=bulk9.com) | `POST /dev/webhook/v2/sms` |
| Webhook (New) | [Update SMS Webhook](https://docs.bulk9.com/reference/update-sms-webhook?domain=bulk9.com) | `PUT /dev/webhook/v2/sms/{id}` |
| Webhook (New) | [Delete SMS Webhook](https://docs.bulk9.com/reference/delete-sms-webhook?domain=bulk9.com) | `DELETE /dev/webhook/v2/sms/{id}` |
| Webhook (New) | [OTP Webhook Overview](https://docs.bulk9.com/reference/otp-webhook?domain=bulk9.com) | Narrative/wrapper |
| Webhook (New) | [List OTP Webhooks](https://docs.bulk9.com/reference/list-otp-webhooks?domain=bulk9.com) | `GET /dev/webhook/v2/otp` |
| Webhook (New) | [Create OTP Webhook](https://docs.bulk9.com/reference/create-otp-webhook?domain=bulk9.com) | `POST /dev/webhook/v2/otp` |
| Webhook (New) | [Update OTP Webhook](https://docs.bulk9.com/reference/update-otp-webhook?domain=bulk9.com) | `PUT /dev/webhook/v2/otp/{id}` |
| Webhook (New) | [Delete OTP Webhook](https://docs.bulk9.com/reference/delete-otp-webhook?domain=bulk9.com) | `DELETE /dev/webhook/v2/otp/{id}` |
| Webhook (New) | [WhatsApp Webhook Overview](https://docs.bulk9.com/reference/whatsapp-webhook?domain=bulk9.com) | Narrative/wrapper |
| Webhook (New) | [List WhatsApp Webhooks](https://docs.bulk9.com/reference/list-whatsapp-webhooks?domain=bulk9.com) | `GET /dev/webhook/v2/whatsapp` |
| Webhook (New) | [Create WhatsApp Webhook](https://docs.bulk9.com/reference/create-whatsapp-webhook?domain=bulk9.com) | `POST /dev/webhook/v2/whatsapp` |
| Webhook (New) | [Update WhatsApp Webhook](https://docs.bulk9.com/reference/update-whatsapp-webhook?domain=bulk9.com) | `PUT /dev/webhook/v2/whatsapp/{id}` |
| Webhook (New) | [Delete WhatsApp Webhook](https://docs.bulk9.com/reference/delete-whatsapp-webhook?domain=bulk9.com) | `DELETE /dev/webhook/v2/whatsapp/{id}` |
| Webhook (New) | [RCS Webhook Overview](https://docs.bulk9.com/reference/rcs-webhook?domain=bulk9.com) | Narrative/wrapper |
| Webhook (New) | [List RCS Webhooks](https://docs.bulk9.com/reference/list-rcs-webhooks?domain=bulk9.com) | `GET /dev/webhook/v2/rcs` |
| Webhook (New) | [Create RCS Webhook](https://docs.bulk9.com/reference/create-rcs-webhook?domain=bulk9.com) | `POST /dev/webhook/v2/rcs` |
| Webhook (New) | [Update RCS Webhook](https://docs.bulk9.com/reference/update-rcs-webhook?domain=bulk9.com) | `PUT /dev/webhook/v2/rcs/{id}` |
| Webhook (New) | [Delete RCS Webhook](https://docs.bulk9.com/reference/delete-rcs-webhook?domain=bulk9.com) | `DELETE /dev/webhook/v2/rcs/{id}` |
| Wallet Balance API | [Wallet Balance](https://docs.bulk9.com/reference/wallet-balance?domain=bulk9.com) | `POST /dev/wallet` |
| Error Codes | [Error Code List](https://docs.bulk9.com/reference/error-code-list?domain=bulk9.com) | Narrative/wrapper |

---

<a id="coverage"></a>

## Coverage verification

On 29 October 2026 the current sidebar inventory was checked against the saved sources: 118 expected pages, 118 retrieved, 96 complete OpenAPI operation pages and no retrieval or OpenAPI parsing failures. Template variants share endpoints, so page count is not function count. There are 64 distinct composed method/path strings before normalizing inconsistent placeholder names. Reseller documentation was reviewed separately: 10 URL patterns and 14 method/path variants. The linked public Postman inventory has 11 requests and adds no operation.

Every public page is listed above with its official source URL. All four detailed section reviews were completed. Source snapshots and schemas were preserved in the original research archive, but are not embedded verbatim in this Markdown file. Review coverage describes the exposed documentation, not hidden partner APIs or verified runtime behavior.
