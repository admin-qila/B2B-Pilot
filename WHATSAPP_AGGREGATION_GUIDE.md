# WhatsApp Message Aggregation Guide

## Problem
When users send multiple images via WhatsApp (using the + button), Twilio sends **separate webhooks for each image**, resulting in:
- 3 separate API calls to webhook-handler
- 3 separate messages sent to SQS
- 3 separate responses to the user
- **Inefficient processing** and poor user experience

## Solution
Implement **message aggregation** using Supabase to collect related messages within a time window and process them together.

---

## How It Works

### Architecture Flow

```
User sends 3 images via WhatsApp
         ↓
Twilio sends 3 separate webhooks (within ~1-2 seconds)
         ↓
┌────────────────────────────────────────────┐
│  Webhook 1 arrives                         │
│  → Create group in Supabase                │
│  → Return "queued" (don't send to SQS yet) │
└────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────┐
│  Webhook 2 arrives (~1 sec later)          │
│  → Add to existing group                   │
│  → Return "queued" (still waiting)         │
└────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────┐
│  Webhook 3 arrives (~1 sec later)          │
│  → Add to group (now has 3 messages)       │
│  → TRIGGER: Max limit reached (3 images)   │
│  → Merge all messages into one             │
│  → Send single message to SQS              │
│  → Delete group from Supabase              │
└────────────────────────────────────────────┘
         ↓
background-processor receives 1 message with 3 images
         ↓
Sends 1 comprehensive analysis to user
```

### Aggregation Logic

Messages are grouped by:
- **Phone number**: Same sender
- **Time window**: Within 5-second bucket

Messages are processed when:
1. **3 messages** accumulated (max limit), OR
2. **3+ seconds** elapsed since first message, OR
3. **5+ seconds** old (processed by stale-message-processor)

---

## Setup Instructions

### 1. Create Supabase Table

Run the migration script:

```bash
psql -h your_host -U your_user -d your_db -f migrations/whatsapp_message_aggregation.sql
```

Or manually in Supabase SQL editor:

```sql
CREATE TABLE IF NOT EXISTS whatsapp_message_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_key TEXT UNIQUE NOT NULL,
    phone_number TEXT NOT NULL,
    messages JSONB NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_group_key ON whatsapp_message_groups(group_key);
CREATE INDEX idx_created_at ON whatsapp_message_groups(created_at);
CREATE INDEX idx_phone_number ON whatsapp_message_groups(phone_number);
```

### 2. Deploy Updated webhook-handler

Files modified:
- `webhook-handler/handler.py` - Added aggregation logic
- `webhook-handler/message_aggregator.py` - New file

Update Lambda environment variables:
- `SUPABASE_URL` - Your Supabase project URL
- `SUPABASE_KEY` - Your Supabase API key

Deploy:
```bash
cd lambda-functions/webhook-handler
# Your deployment command (e.g., serverless deploy, SAM deploy, etc.)
```

### 3. Deploy stale-message-processor (Optional but Recommended)

This Lambda runs on a schedule to process messages that didn't reach thresholds.

Create new Lambda function:
- **Function name**: `whatsapp-stale-message-processor`
- **Runtime**: Python 3.x
- **Handler**: `handler.lambda_handler`
- **Code**: Upload `lambda-functions/stale-message-processor/handler.py`
- **Environment variables**:
  - `SUPABASE_URL`
  - `SUPABASE_KEY`
  - `SQS_QUEUE_URL`

### 4. Create CloudWatch Events Rule

Schedule the stale-message-processor to run every 10 seconds:

```bash
aws events put-rule \
  --name whatsapp-stale-message-processor-schedule \
  --schedule-expression 'rate(10 seconds)'

aws events put-targets \
  --rule whatsapp-stale-message-processor-schedule \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT:function:whatsapp-stale-message-processor"
```

Or via AWS Console:
1. Go to CloudWatch → Events → Rules
2. Create rule with schedule: `rate(10 seconds)`
3. Add target: Your stale-message-processor Lambda

---

## Testing

### Test Case 1: Send 3 Images Together

1. Open WhatsApp
2. Click the + button
3. Select 3 images
4. Send

**Expected Result:**
- Webhook-handler receives 3 webhooks
- First 2 return immediately (queued)
- Third triggers processing
- **1 message** sent to SQS with **3 media items**
- **1 response** sent to user

**Verify in logs:**
```
Processing message from +1234567890 with 1 media items
Created new message group +1234567890#1234567890
Message added to group, waiting for more messages

Processing message from +1234567890 with 1 media items
Added message to existing group +1234567890#1234567890. Total: 2
Message added to group, waiting for more messages

Processing message from +1234567890 with 1 media items
Added message to existing group +1234567890#1234567890. Total: 3
Processing aggregated message with 3 items
Merged 3 messages into one with 3 media items
Message queued successfully
```

### Test Case 2: Send 2 Images

1. Send 2 images via WhatsApp
2. Wait 3-4 seconds

**Expected Result:**
- First webhook creates group
- Second webhook adds to group
- After 3 seconds, time threshold triggers processing
- **1 message** sent to SQS with **2 media items**

### Test Case 3: Send 1 Image

1. Send single image via WhatsApp
2. Wait 5-10 seconds

**Expected Result:**
- Webhook creates group
- No other messages arrive
- After 5 seconds, stale-message-processor picks it up
- **1 message** sent to SQS with **1 media item**

---

## Configuration

### Time Windows

Adjust in `message_aggregator.py`:

```python
# Grouping window (messages within this window are grouped)
time_window = 5  # seconds (line 70)

# Processing delay threshold
time_elapsed > 3  # seconds (line 107)

# Stale message age
max_age_seconds = 5  # seconds (line 180)
```

### Message Limits

```python
# Maximum images per message
should_process = len(messages) >= 3  # line 107
merged['media_items'] = all_media_items[:3]  # line 169
```

---

## Monitoring

### Supabase Query - Check Active Groups

```sql
SELECT * FROM whatsapp_message_groups 
ORDER BY created_at DESC;
```

### Supabase Query - Find Stale Groups

```sql
SELECT 
    group_key, 
    phone_number, 
    message_count,
    created_at,
    EXTRACT(EPOCH FROM (NOW() - created_at)) as age_seconds
FROM whatsapp_message_groups
WHERE created_at < NOW() - INTERVAL '5 seconds'
ORDER BY created_at;
```

### CloudWatch Logs

**webhook-handler logs:**
```
# Search for aggregation activity
filter @message like /group/
filter @message like /aggregat/
filter @message like /Merged/
```

**stale-message-processor logs:**
```
# Check stale message processing
filter @message like /stale/
filter @message like /Processed.*messages/
```

### Metrics to Track

1. **Messages aggregated** - Count of merged message groups
2. **Average images per group** - Typical multi-image sends
3. **Stale message rate** - How often timeout triggers
4. **Group table size** - Should stay near 0 most of the time

---

## Troubleshooting

### Issue: Messages not aggregating

**Symptoms:** Still getting 3 separate responses

**Checks:**
1. Verify Supabase table exists
2. Check environment variables set
3. Look for errors in webhook-handler logs
4. Verify `should_aggregate()` returns True

**Debug:**
```python
# Add to webhook-handler logs
logger.info(f"Should aggregate: {aggregator.should_aggregate(unified_message)}")
logger.info(f"Group key: {group_key}")
```

### Issue: Messages stuck in Supabase

**Symptoms:** Groups never get processed

**Checks:**
1. Verify stale-message-processor is deployed
2. Check CloudWatch Events rule is active
3. Look for errors in stale-processor logs

**Manual fix:**
```sql
-- Force process all stuck messages
SELECT * FROM whatsapp_message_groups;
-- Then delete them
DELETE FROM whatsapp_message_groups WHERE created_at < NOW() - INTERVAL '1 minute';
```

### Issue: Duplicate processing

**Symptoms:** User receives multiple responses

**Checks:**
1. Verify group deletion happens after processing
2. Check for race conditions in logs
3. Ensure stale-processor doesn't overlap with webhook processing

---

## Performance Considerations

### Database Load

- **Writes**: 1-3 per user message group
- **Reads**: 1 per incoming webhook
- **Deletes**: 1 per processed group
- **Expected QPS**: Low (< 10/sec for small deployments)

### Cold Starts

First webhook might be slow due to Lambda cold start, but subsequent webhooks (1-2 seconds later) will be warm.

### Cost Impact

**Additional costs:**
- Supabase: Minimal (< 100 rows typically)
- Lambda: stale-message-processor runs every 10 seconds
- CloudWatch Events: ~8,640 invocations/day

**Savings:**
- Reduced OpenAI API calls (1 instead of 3)
- Reduced SQS messages
- Reduced Lambda background-processor invocations

**Net result:** Cost savings overall!

---

## Alternative Approaches

### Option 1: Client-side aggregation (Not recommended)
WhatsApp doesn't support this - Twilio always sends separate webhooks.

### Option 2: SQS message deduplication (Not suitable)
Can't aggregate across multiple messages, only deduplicate exact duplicates.

### Option 3: Step Functions (More complex)
Could use Step Functions with wait states, but adds complexity and cost.

### Option 4: Redis/ElastiCache (Alternative to Supabase)
Similar pattern but requires separate Redis instance.

---

## Summary

✅ **Benefits:**
- Single comprehensive analysis of all images
- Better user experience (1 response instead of 3)
- Cost savings (1 OpenAI call instead of 3)
- Scalable solution

✅ **Trade-offs:**
- Small delay (1-5 seconds) for aggregation
- Additional Supabase table
- Extra Lambda for stale processing

✅ **Best for:**
- Users frequently sending 2-3 images
- Cost-conscious deployments
- Production-ready systems
