-- Migration: Add message_id column for idempotent message processing
-- Description: This migration adds a message_id column to track SNS message IDs
--              and prevent duplicate processing due to SNS's at-least-once delivery

-- Add message_id column to b2b_pilot_user_submissions table
ALTER TABLE b2b_pilot_user_submissions
ADD COLUMN IF NOT EXISTS message_id VARCHAR(255);

-- Create unique index on message_id to enforce idempotency
-- This will prevent duplicate processing of the same SNS message
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_submissions_message_id 
ON b2b_pilot_user_submissions(message_id) 
WHERE message_id IS NOT NULL;

-- Add index for performance on lookups
CREATE INDEX IF NOT EXISTS idx_user_submissions_message_id_lookup 
ON b2b_pilot_user_submissions(message_id);

-- Add comment to explain the column
COMMENT ON COLUMN b2b_pilot_user_submissions.message_id IS 
'SNS Message ID for idempotent processing. Ensures at-least-once delivery does not result in duplicate submissions.';
