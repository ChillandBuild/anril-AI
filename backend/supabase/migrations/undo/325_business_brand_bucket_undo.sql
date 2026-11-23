-- Undo 325: remove the pictures, then the bucket. (Bills keep working; they just lose the logo.)
DELETE FROM storage.objects WHERE bucket_id = 'business-brand';
DELETE FROM storage.buckets WHERE id = 'business-brand';
