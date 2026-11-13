-- 266: each character answers with its own AI model.
--
-- The model ID is plain text (e.g. 'google/gemini-3.5-flash-lite'), checked by the backend against
-- ai_reply.REPLY_MODELS, so adding a model later is one line of code and no migration.
-- Every character has one. Existing characters get the model they already answer with: the
-- business's app_settings.ai_reply_model when it is a known ID, else Gemini 3.1 Flash Lite (the default).
--
-- Example: a business with ai_reply_model = 'google/gemini-3.1-flash-lite' and two characters →
-- both rows get 'google/gemini-3.1-flash-lite'; the owner later switches one to 3.5 in the editor
-- or with "Use for <character>" in the Playground, and only that character's replies change.
-- Safe in either deploy order: the old backend ignores the column, the new one falls back to the default.
alter table public.companions
  add column if not exists model text not null default 'google/gemini-3.1-flash-lite';

update public.companions c
   set model = s.value
  from public.app_settings s
 where s.tenant_id = c.tenant_id
   and s.key = 'ai_reply_model'
   and s.value in ('google/gemini-3.1-flash-lite', 'google/gemini-3.5-flash-lite');

comment on column public.companions.model is
  'The AI model this character replies with (an ai_reply.REPLY_MODELS id). The Playground can try another without saving.';
