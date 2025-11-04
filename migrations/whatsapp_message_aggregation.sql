-- Create table for WhatsApp message aggregation
-- This table temporarily stores messages that arrive within a short time window
-- so they can be processed together as a single multi-media message

CREATE TABLE IF NOT EXISTS whatsapp_message_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_key TEXT UNIQUE NOT NULL,  -- phone_number#timestamp
    phone_number TEXT NOT NULL,
    messages JSONB NOT NULL,  -- Array of message objects
    message_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast lookup by group_key
CREATE INDEX IF NOT EXISTS idx_group_key ON whatsapp_message_groups(group_key);

-- Index for finding stale messages
CREATE INDEX IF NOT EXISTS idx_created_at ON whatsapp_message_groups(created_at);

-- Index for phone number lookups
CREATE INDEX IF NOT EXISTS idx_phone_number ON whatsapp_message_groups(phone_number);

-- Add comment to table
COMMENT ON TABLE whatsapp_message_groups IS 'Temporary storage for aggregating multiple WhatsApp media messages sent within a short time window';

-- Add comments to columns
COMMENT ON COLUMN whatsapp_message_groups.group_key IS 'Unique key: phone_number#timestamp (5-second window)';
COMMENT ON COLUMN whatsapp_message_groups.messages IS 'Array of UnifiedMessage objects as JSON';
COMMENT ON COLUMN whatsapp_message_groups.message_count IS 'Number of messages in this group';
COMMENT ON COLUMN whatsapp_message_groups.created_at IS 'When the first message in group arrived';
COMMENT ON COLUMN whatsapp_message_groups.last_updated_at IS 'When the last message was added to group';
