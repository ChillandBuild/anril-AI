# SMS API contract — client-only Bulk9 integration

Approved scope: `2026-10-30-sms-client-only.md`. Schema: `backend/supabase/migrations/237_sms_bulk9.sql` (not applied to the live database). Provider wrapper: `backend/app/services/bulk9_client.py`.

Bulk9 owns accounts, pricing, payments, credit allocation, stock and profit. Anril exposes SMS counts and delivery information. No monetary values are returned by these SMS APIs or exported to CSV. Times are ISO-8601 UTC; the UI shows IST.

Per-tenant settings retained: `bulk9_api_key` (secret), `bulk9_webhook_secret` (secret), webhook registration state, `sms_checklist` (JSON with dlt/pe_tm/sender flags), and `sms_support_contact`. The migration blocks direct authenticated access to settings beginning with `sms_` or `bulk9_`; the server uses the service role. SMS is enabled when `sms` appears in `tenants.enabled_features`.

## Client API — prefix `/api/v1/sms`

Every route needs a logged-in tenant member. Except GET /status, a tenant without "sms" enabled
gets 403 {"detail": "SMS is not enabled for this account"}; a tenant with no key gets 409
{"detail": "SMS is not connected yet"} on routes that call Bulk9.
Permissions: reads require `sms.view`; writes require `sms.manage`. Preview uses `sms.view`. Developer key access requires the tenant owner. Cached reads and campaign preview do not require a provider key; provider operations do.

| Method path | Body / query | Response |
|---|---|---|
| GET /status | – | {enabled, connected, checklist:{dlt,pe_tm,sender}, support_contact} |
| GET /balance | – | {sms_count: int} |
| GET /senders | – | {senders:[{sender_id, entity_id, entity_name}]} |
| GET /templates | – | {templates:[Template], last_synced_at, error: string\|null} |
| POST /templates/refresh | – | same as GET /templates (on Bulk9 failure: keeps cached rows, error set, HTTP 200) |
| PATCH /templates/{id} | {template_type:"service"\|"promotional"} | Template |
| POST /dlt/entity | multipart: entity_name, entity_id, files (1–5, ≤20MB each; jpg/jpeg/png/gif/pdf/doc/docx/odt) | {ok:true, message} |
| POST /dlt/sender | {entity_id, sender_id (3–6 chars)} | {ok:true, message} |
| POST /dlt/sender-excel | multipart: entity_id, file (.xlsx/.csv DLT export) | {ok:true, message} |
| POST /dlt/template | {entity_id, sender_ids:[str], dlt_template_id, message_text, template_type} | {ok:true, message} — also inserts a `submitted` sms_templates row |
| POST /dlt/template-excel | multipart: entity_id, file, template_type | {ok:true, message} |
| GET /template-requests | – | {requests:[{id, wording, template_type, status, reason, created_at, updated_at}]} |
| POST /template-requests | {wording, template_type} | request row |
| GET /campaigns/fields | – | {fields:[{key, label}]} — lead fields usable as variables, e.g. {"key":"name","label":"Name"} |
| POST /campaigns/preview | {template_id, variable_map:[VarSource], lead_ids:[uuid] (≤5000)} | Preview |
| POST /campaigns | {name, template_id, variable_map, lead_ids, send_at: ISO\|null, idempotency_key} | Campaign (201). Same idempotency_key again → the existing campaign, 200 |
| GET /campaigns | ?limit=50&offset=0 | {campaigns:[Campaign]} |
| GET /campaigns/{id} | – | Campaign |
| POST /campaigns/{id}/cancel | – | Campaign (only while status=scheduled; queued messages → cancelled) |
| GET /messages | ?campaign_id&status&from&to&search&limit=50&offset=0 | {messages:[Message], total} |
| GET /messages/export.csv | same filters | text/csv |
| GET /reports/summary | ?from&to (YYYY-MM-DD, ≤30 days) | {anril:{status:count…}, bulk9: financially scrubbed summary\|null, error} |
| GET /reports/logs | ?from&to (≤3 days)&page&limit | {logs: flattened, financially scrubbed Bulk9 recipient rows, page, error} |
| GET /developer/key | owner only | {api_key} |
| POST /otp/send | {mobile, otp_id, otp_length=6, otp_expiry=15} | {ok, request_id, message} |
| POST /otp/verify | {mobile, otp} | {ok, message} |
| POST /otp/resend | {mobile} | {ok, message} |

Types

- Template: {id, message_id, dlt_template_id, sender_id, entity_id, entity_name, message, var_count, template_type:"service"|"promotional"|"unclassified", status:"ready"\|"submitted", last_synced_at}
- VarSource: {source:"field", value:"name"} or {source:"text", value:"2 Nov"} — one per {#var#}, in order
- Preview: {eligible_count, excluded:[{lead_id, name, phone, reason}], samples:[{lead_id, name, content, segments, unicode}] (≤3), total_segments: int, estimated: true}
  Exclusion reasons (exact strings): "Opted out", "No SMS consent (promotional template)", "Not an Indian mobile number", "Missing value for {field}", "Duplicate number"
- Campaign: {id, name, template_text, sender_id, template_type, status:"scheduled"\|"sending"\|"completed"\|"cancelled", send_at, created_at, completed_at, counts:{queued, sending, submitted, delivered, failed, unknown, skipped, cancelled}, total}
- Message: {id, campaign_id, lead_id, lead_name, phone, content, status, failure_reason, sms_count, submitted_at, delivered_at, updated_at}

Message status meaning for the UI: queued "Waiting", sending "Sending", submitted "Sent to operator",
delivered "Delivered", failed "Failed" (+ reason),
unknown "Checking…" (never a resend button), skipped "Not sent" (+ reason), cancelled "Cancelled".

## Sending and delivery behavior

Newly synced templates start as `unclassified`; a user must choose service or promotional before sending. Promotional sends require recorded consent, its source and its date; eligibility is checked again immediately before sending. Schedules must be in the future.

Ambiguous provider outcomes remain `unknown` (shown as “Checking…”), and are never automatically resent. Reconciliation reads paginated provider logs and the documented nested delivery rows; an absent row does not prove a send failed. Automatic reconciliation covers the existing seven-day window; later authenticated callbacks can still resolve a message. Provider financial fields are removed from client reports and delivery audit storage.

DLT forms import approved entity/sender/template information into Bulk9. New telecom DLT approvals and PE–TM binding still require the operator portals or Bulk9 dashboard, as the vendor email explains. A submitted local template is not ready for campaign use until it appears in the provider's usable template list. New-wording requests are handled by an operator outside Anril and tracked in Anril.

## Operator API — prefix `/api/v1/operator`

All routes require the system administrator. The UI is in **Client → Configuration → SMS connection**. The existing general feature control enables/disables the SMS feature; no dedicated SMS reseller panel remains.

| Method path | Body / query | Response |
|---|---|---|
| GET /clients/{tenant_id}/sms | – | ConnectionState |
| PUT /clients/{tenant_id}/sms/key | {api_key} | ConnectionState; validates provider SMS credits, saves key, attempts webhook registration |
| POST /clients/{tenant_id}/sms/webhook | – | ConnectionState; retries webhook registration |
| GET /clients/{tenant_id}/sms/template-requests | ?page=1&limit=50 | {items:[TemplateRequest], total, page, limit} |
| PATCH /clients/{tenant_id}/sms/template-requests/{request_id} | {status:"in_progress"|"ready"|"rejected", reason?:string} | {item:TemplateRequest} |

ConnectionState: `{connected:bool, key_masked:string|null, webhook_registered:bool, webhook_error:string|null}`. The frontend permits an optional SMS count, but the current operator state returns these four fields. New template requests begin as `requested`.

Webhook registration derives the callback URL from trusted deployment configuration, reuses the tenant's existing secret and matching callback, and fails closed if the provider response cannot be understood. An unconfirmed registration is shown honestly with a retry action.

No SMS account creation, reseller administration, price settings, credits/debits, ledger, recharge, payment, stock or profit endpoints remain in Anril. General application payments and Razorpay OAuth are unchanged.

## Delivery callback

`POST /webhook/bulk9/{tenant_id}` accepts the existing provider delivery format, checks the `X-Anril-Webhook-Secret` header against the per-tenant secret with a constant-time comparison, limits the request body to 64 KiB and records redacted delivery events. There is no SMS payment callback. See `backend/app/routes/sms_webhooks.py` for the canonical callback path.
