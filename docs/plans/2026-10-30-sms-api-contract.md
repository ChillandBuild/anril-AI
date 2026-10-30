# SMS API contract (workers build against this)

Plan: docs/plans/2026-10-30-bulk9-sms-full-build.md. Schema: backend/supabase/migrations/237_sms_bulk9.sql.
Bulk9 wrappers: backend/app/services/bulk9_client.py, bulk9_reseller.py. All money values are
JSON numbers in rupees (2–4 decimals). Times are ISO-8601 UTC; the UI shows IST.

Per-tenant app_settings keys (non-secret unless marked): bulk9_api_key (secret), bulk9_username,
bulk9_webhook_secret (secret), sms_price_per_sms (default "0.25"), sms_buy_rate,
sms_checklist (JSON {"dlt":bool,"pe_tm":bool,"sender":bool}), sms_support_contact.
SMS is "enabled" for a tenant when "sms" is in tenants.enabled_features.

## Client API — prefix /api/v1/sms (owner: backend worker A; except Recharge = planner)

Every route needs a logged-in tenant member. Except GET /status, a tenant without "sms" enabled
gets 403 {"detail": "SMS is not enabled for this account"}; a tenant with no key gets 409
{"detail": "SMS is not connected yet"} on routes that call Bulk9.
Permission: GET routes sms.view; writes sms.manage; recharge sms.recharge; developer key owner only.

| Method path | Body / query | Response |
|---|---|---|
| GET /status | – | {enabled, connected, checklist:{dlt,pe_tm,sender}, price_per_sms, support_contact} |
| GET /balance | – | {wallet: number, sms_count: int, price_per_sms} |
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
| GET /reports/summary | ?from&to (YYYY-MM-DD, ≤30 days) | {anril:{status:count…}, bulk9: raw summary\|null, error} |
| GET /reports/logs | ?from&to (≤3 days)&page&limit | {logs: raw Bulk9 rows, page, error} |
| GET /ledger | ?limit&offset | {entries:[{id, kind, sms_count, price_per_sms, amount, expiry_date, note, created_at}]} (no buy_rate) |
| GET /developer/key | owner only | {api_key} |
| POST /otp/send | {mobile, otp_id, otp_length=6, otp_expiry=15} | {ok, request_id, message} |
| POST /otp/verify | {mobile, otp} | {ok, message} |
| POST /otp/resend | {mobile} | {ok, message} |
| GET /recharge/packs | – | {packs:[{amount_rupees, sms_count, price_per_sms}]} (planner) |
| POST /recharge | {amount_rupees} | {payment_id, short_url} (planner) |
| GET /recharge/payments | – | {payments:[{id, amount_rupees, sms_count, status, short_url, created_at, credited_at, error}]} (planner) |

Types
- Template: {id, message_id, dlt_template_id, sender_id, entity_id, entity_name, message, var_count, template_type, status:"ready"\|"submitted", last_synced_at}
- VarSource: {source:"field", value:"name"} or {source:"text", value:"2 Nov"} — one per {#var#}, in order
- Preview: {eligible_count, excluded:[{lead_id, name, phone, reason}], samples:[{lead_id, name, content, segments, unicode}] (≤3), price_per_sms, estimated_total: number, estimated: true}
  Exclusion reasons (exact strings): "Opted out", "No SMS consent (promotional template)", "Not an Indian mobile number", "Missing value for {field}", "Duplicate number"
- Campaign: {id, name, template_text, sender_id, template_type, status:"scheduled"\|"sending"\|"completed"\|"cancelled", send_at, created_at, completed_at, counts:{queued, sending, submitted, delivered, failed, unknown, skipped, cancelled}, total, charged_total}
- Message: {id, campaign_id, lead_id, lead_name, phone, content, status, failure_reason, sms_count, charged_amount, submitted_at, delivered_at, updated_at}  (no cost_amount)

Message status meaning for the UI: queued "Waiting", sending "Sending", submitted "Sent to operator",
delivered "Delivered", failed "Failed" (+ reason; show "charged ₹x" when charged_amount>0),
unknown "Checking…" (never a resend button), skipped "Not sent" (+ reason), cancelled "Cancelled".

## Operator API — prefix /api/v1/operator (planner writes; operator UI worker C builds against it)

All need get_system_admin.

| Method path | Body | Response |
|---|---|---|
| GET /clients/{tenant_id}/sms | – | OperatorSms |
| POST /clients/{tenant_id}/sms/account | {username, name, email?, mobile?} | OperatorSms (creates Bulk9 user, saves bulk9_username) |
| PUT /clients/{tenant_id}/sms/key | {api_key} | OperatorSms (tests wallet, saves, registers delivery webhook) |
| PATCH /clients/{tenant_id}/sms/settings | {bulk9_username?, price_per_sms?, buy_rate?, checklist?, support_contact?} | OperatorSms |
| POST /clients/{tenant_id}/sms/enable | – | OperatorSms (adds "sms" feature + Bulk9 enable) |
| POST /clients/{tenant_id}/sms/disable | – | OperatorSms |
| POST /clients/{tenant_id}/sms/webhook | – | OperatorSms (re-register delivery webhook) |
| POST /clients/{tenant_id}/sms/credit | {kind:"manual_credit"\|"bonus", sms_count, price_per_sms?, expiry_date?, note?} | OperatorSms |
| POST /clients/{tenant_id}/sms/debit | {sms_count, note?} | OperatorSms |
| PATCH /clients/{tenant_id}/sms/template-requests/{id} | {status:"in_progress"\|"ready"\|"rejected", reason?} | OperatorSms |
| GET /sms/stock | – | {sms_count, sms_balance, threshold, low, error} |

OperatorSms: {enabled, connected, key_masked, bulk9_username, webhook_registered, price_per_sms,
buy_rate, checklist, support_contact, balance:{wallet, sms_count}\|null, balance_error,
ledger:[{… , buy_rate}], template_requests:[…], profit:{sms_sold, revenue, cost, profit}}
