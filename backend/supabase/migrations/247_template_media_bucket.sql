-- Our own copy of template header media (image/video/document).
-- Meta's example link for a synced template is a signed scontent.whatsapp.net
-- URL that expires (its oe= param), and an in-app upload only gives a Meta
-- upload handle, which Meta can't fetch at send time. Every send of a media
-- header must carry a link Meta can download, so we keep the file here and
-- store this bucket's permanent public URL in message_templates.header_media_url.
-- Public read: these images are sent to customers anyway. Writes go through the
-- backend's service-role key only (no insert/update/delete policy for users).
insert into storage.buckets (id, name, public)
values ('template-media', 'template-media', true)
on conflict (id) do nothing;
