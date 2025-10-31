# WhatsApp Message Aggregation - Setup Checklist

## Quick Setup (15 minutes)

### ☐ 1. Database Setup (5 min)

```bash
# Run migration in Supabase
psql -h your_host -U your_user -d your_db -f migrations/whatsapp_message_aggregation.sql
```

**Or** run in Supabase SQL Editor:
```sql
CREATE TABLE IF NOT EXISTS whatsapp_message_groups (...);
-- See migrations/whatsapp_message_aggregation.sql for full SQL
```

**Verify:**
```sql
SELECT * FROM whatsapp_message_groups;
-- Should return empty table with correct schema
```

---

### ☐ 2. Deploy webhook-handler (5 min)

**Files changed:**
- ✅ `lambda-functions/webhook-handler/handler.py` (modified)
- ✅ `lambda-functions/webhook-handler/message_aggregator.py` (new)

**Environment variables needed:**
- `SUPABASE_URL` = your_supabase_url
- `SUPABASE_KEY` = your_supabase_key  
- `SQS_QUEUE_URL` = existing_sqs_queue_url

**Deploy command:**
```bash
cd lambda-functions/webhook-handler
# Run your deploy command
# Example: serverless deploy
# Example: sam build && sam deploy
```

**Test:**
Send a single image via WhatsApp and check CloudWatch logs for:
```
Created new message group +1234567890#...
```

---

### ☐ 3. Deploy stale-message-processor (5 min)

**Option A: Deploy with SAM (Recommended)**

The stale-message-processor is already included in `template.yaml`!

Just deploy your entire stack:
```bash
cd lambda-functions
sam build
sam deploy --guided
```

The processor will automatically:
- Be created as a Lambda function
- Have the correct environment variables
- Run every 10 seconds via CloudWatch Events
- Have CloudWatch alarms configured

**Option B: Manual Deployment**

**Create new Lambda:**
- Function name: `whatsapp-stale-message-processor`
- Runtime: Python 3.9+
- Handler: `handler.lambda_handler`
- Code: Upload `lambda-functions/stale-message-processor/`
- Timeout: 30 seconds
- Memory: 256 MB

**Environment variables:**
- `SUPABASE_URL` = your_supabase_url
- `SUPABASE_KEY` = your_supabase_key
- `SQS_QUEUE_URL` = your_sqs_queue_url

**Create CloudWatch Events trigger:**
```bash
aws events put-rule \
  --name whatsapp-stale-message-schedule \
  --schedule-expression 'rate(10 seconds)'

aws events put-targets \
  --rule whatsapp-stale-message-schedule \
  --targets "Id"="1","Arn"="YOUR_LAMBDA_ARN"

aws lambda add-permission \
  --function-name whatsapp-stale-message-processor \
  --statement-id AllowCloudWatchInvoke \
  --action 'lambda:InvokeFunction' \
  --principal events.amazonaws.com \
  --source-arn YOUR_RULE_ARN
```

**Test:**
Invoke manually and check response:
```json
{
  "statusCode": 200,
  "body": "{\"processed\": 0, \"message\": \"No stale messages\"}"
}
```

---

## Testing Checklist

### ☐ Test 1: Single Image
- [ ] Send 1 image via WhatsApp
- [ ] Wait 5-10 seconds
- [ ] Should receive 1 response
- [ ] Check logs: `Created new message group`
- [ ] Check logs: `Processed stale message group` (from stale-processor)

### ☐ Test 2: Two Images
- [ ] Send 2 images together via WhatsApp
- [ ] Wait 3-5 seconds
- [ ] Should receive 1 response
- [ ] Check logs: `Added message to existing group. Total: 2`
- [ ] Check logs: `Merged 2 messages into one with 2 media items`

### ☐ Test 3: Three Images (Main Test)
- [ ] Send 3 images together via WhatsApp
- [ ] Should receive 1 response within 2-3 seconds
- [ ] Check logs: `Added message to existing group. Total: 3`
- [ ] Check logs: `Processing aggregated message with 3 items`
- [ ] Verify background-processor receives 1 message with 3 images

---

## Verification Queries

### Check Supabase for active groups
```sql
SELECT 
    group_key,
    phone_number,
    message_count,
    created_at,
    EXTRACT(EPOCH FROM (NOW() - created_at)) as age_seconds
FROM whatsapp_message_groups
ORDER BY created_at DESC
LIMIT 10;
```

**Expected:** Usually 0 rows (groups are deleted after processing)

### Find any stuck groups
```sql
SELECT * FROM whatsapp_message_groups
WHERE created_at < NOW() - INTERVAL '1 minute';
```

**Expected:** 0 rows (stale-processor should clean these up)

---

## Rollback Plan

If something goes wrong:

### Quick Disable
```python
# In webhook-handler/handler.py, change:
if aggregator.should_aggregate(unified_message):
# To:
if False:  # Temporarily disable aggregation
```

Redeploy webhook-handler.

### Full Rollback
1. Revert webhook-handler to previous version
2. Delete CloudWatch Events rule
3. Delete stale-message-processor Lambda
4. (Optional) Drop Supabase table:
   ```sql
   DROP TABLE IF EXISTS whatsapp_message_groups;
   ```

---

## Success Criteria

✅ **Working correctly when:**
1. Sending 3 images via WhatsApp results in 1 response (not 3)
2. Supabase table stays mostly empty (< 5 rows at any time)
3. No errors in CloudWatch logs
4. Background-processor receives consolidated messages
5. Users receive comprehensive analysis of all images together

✅ **Performance metrics:**
- Response time: 2-5 seconds for 3 images
- Database rows: < 10 active groups at peak
- Stale processing: < 10% of messages
- User satisfaction: Single response instead of multiple

---

## Common Issues & Quick Fixes

### Issue: Still getting 3 responses
**Fix:** Check webhook-handler logs for aggregation activity
```bash
# Search logs for:
"should_aggregate"
"Created new message group"
```

### Issue: Messages stuck in Supabase
**Fix:** Verify stale-processor is running every 10 seconds
```bash
# Check CloudWatch Events rule status
aws events list-rules --name-prefix whatsapp-stale
```

### Issue: Supabase connection errors
**Fix:** Verify environment variables
```bash
# In Lambda console, check:
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJxxx...
```

---

## Next Steps After Setup

1. **Monitor for 24 hours** - Check CloudWatch logs and Supabase
2. **Adjust timing** - Tune aggregation windows if needed
3. **Add metrics** - Track aggregation success rate
4. **Document** - Share with team

---

## Support Files

- 📄 `WHATSAPP_AGGREGATION_GUIDE.md` - Full documentation
- 🗄️ `migrations/whatsapp_message_aggregation.sql` - Database schema
- 💻 `lambda-functions/webhook-handler/message_aggregator.py` - Aggregation logic
- ⏰ `lambda-functions/stale-message-processor/handler.py` - Cleanup job
