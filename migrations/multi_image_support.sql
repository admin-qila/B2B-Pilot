-- Migration: Convert image_url and s3_key columns to JSONB for multi-image support
-- This maintains backward compatibility while enabling storage of multiple images

-- Backup recommendation: Create a backup before running this migration
-- pg_dump -h your_host -U your_user -d your_db -t b2b_pilot_user_submissions > backup_before_jsonb_migration.sql

BEGIN;

-- Convert image_url column from TEXT to JSONB
-- Existing single URLs will be stored as JSON strings: "https://example.com/image.jpg"
-- Multiple URLs will be stored as JSON arrays: ["url1", "url2", "url3"]
ALTER TABLE b2b_pilot_user_submissions 
ALTER COLUMN image_url TYPE JSONB USING 
  CASE 
    WHEN image_url IS NULL THEN NULL
    WHEN image_url::text LIKE '[%' THEN image_url::jsonb
    ELSE to_jsonb(image_url::text)
  END;

-- Convert s3_key column from TEXT to JSONB
-- Existing single keys will be stored as JSON strings: "path/to/image.jpg"
-- Multiple keys will be stored as JSON arrays: ["key1", "key2", "key3"]
ALTER TABLE b2b_pilot_user_submissions 
ALTER COLUMN s3_key TYPE JSONB USING 
  CASE 
    WHEN s3_key IS NULL THEN NULL
    WHEN s3_key::text LIKE '[%' THEN s3_key::jsonb
    ELSE to_jsonb(s3_key::text)
  END;

-- Optional: Create indexes for better query performance on JSONB columns
-- Uncomment if you need to query these fields frequently
-- CREATE INDEX IF NOT EXISTS idx_image_url_jsonb ON b2b_pilot_user_submissions USING gin(image_url);
-- CREATE INDEX IF NOT EXISTS idx_s3_key_jsonb ON b2b_pilot_user_submissions USING gin(s3_key);

COMMIT;

-- Verification queries:
-- Check data types after migration
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'b2b_pilot_user_submissions' 
-- AND column_name IN ('image_url', 's3_key');

-- Check sample data to verify conversion
-- SELECT id, image_url, s3_key, jsonb_typeof(image_url) as url_type, jsonb_typeof(s3_key) as key_type
-- FROM b2b_pilot_user_submissions 
-- LIMIT 10;
