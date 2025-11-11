# Migration Guide: SQS to SNS Architecture

## Overview

This migration moves the B2B Pilot message processing system from **AWS SQS (Simple Queue Service)** to **AWS SNS (Simple Notification Service)** to achieve:

1. ✅ **Near-instant, low-latency message processing** - SNS directly invokes Lambda with no polling delay
2. ✅ **Reliable, durable delivery with retries** - Lambda DLQ handles failed messages after retries
3. ✅ **Idempotent processing** - Database-backed deduplication prevents duplicate processing
4. ✅ **Optional fan-out** - SNS supports multiple subscribers (future scaling)
5. ✅ **Cost-efficiency** - No charges for empty queue polling, pay per message

## Architecture Changes

### Before (SQS)
```
Webhook → SQS Queue → Lambda Poller (batched) → Processing
         ↓
    Dead Letter Queue
```

### After (SNS)
```
Webhook → SNS Topic → Lambda (direct invocation) → Processing
                     ↓
              Lambda DLQ (SQS)
```

## Key Differences

| Feature | SQS | SNS |
|---------|-----|-----|
| **Latency** | Polling delay (1-20s) | Near-instant (~ms) |
| **Delivery** | Pull-based | Push-based |
| **Cost** | Polling charges | Pay per publish |
| **Retries** | Built-in with visibility timeout | Lambda retries + DLQ |
| **Fan-out** | Single consumer | Multiple subscribers |
| **Idempotency** | MessageId + deduplication | Custom implementation needed |

## Changes Made

### 1. Infrastructure (template.yaml)

**Replaced:**
- `MessageQueue` (SQS) → `MessageTopic` (SNS)
- SQS event source → SNS event source for ProcessorFunction
- Queue depth alarm → SNS failed delivery alarm

**Added:**
- `ReservedConcurrentExecutions: 10` on ProcessorFunction for cost control
- Lambda DLQ configuration for failed message handling

### 2. Database Schema

**Added column to `b2b_pilot_user_submissions`:**
```sql
message_id VARCHAR(255) -- Unique constraint for idempotency
```

Run the migration:
```bash
psql -h <your-db-host> -U <user> -d <database> -f migrations/add_message_id_column.sql
```

### 3. Code Changes

#### webhook-handler/handler.py
- Changed from `boto3.client('sqs')` to `boto3.client('sns')`
- Replaced `sqs.send_message()` with `sns.publish()`
- Added unique `message_id` generation (UUID)
- Added SNS message attributes for filtering

#### background-processor/handler.py
- Updated event parsing for SNS format (instead of SQS)
- Added idempotency check using `message_id` in database
- Updated error handling to raise exceptions for DLQ
- Added `get_submission_by_message_id()` method

#### background-processor/models.py
- Added `message_id` field to `UserSubmission` dataclass
- Added `get_submission_by_message_id()` method to DatabaseManager
- Updated `create_submission()` to store `message_id`

#### stale-message-processor/handler.py
- Changed from SQS to SNS publishing
- Added message_id generation
- Updated message attributes

#### webhook-handler/config.py
- Changed `SQS_QUEUE_URL` to `SNS_TOPIC_ARN`
- Removed SQS-specific configurations

## Deployment Steps

### Prerequisites
1. Run the database migration
2. Update SAM/CloudFormation parameters (no changes needed if using template params)

### Deploy

```bash
cd lambda-functions

# Build
sam build

# Deploy (adjust parameters as needed)
sam deploy \
  --guided \
  --stack-name b2b-pilot-prod \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    Environment=prod \
    TwilioAccountSid=$TWILIO_ACCOUNT_SID \
    TwilioAuthToken=$TWILIO_AUTH_TOKEN \
    # ... other parameters
```

### Post-Deployment Verification

1. **Check SNS Topic:**
```bash
aws sns list-topics | grep b2b-pilot-messages
```

2. **Check Lambda subscription:**
```bash
aws sns list-subscriptions-by-topic \
  --topic-arn <your-topic-arn>
```

3. **Test webhook:**
```bash
curl -X POST <your-webhook-url> \
  -H "Content-Type: application/json" \
  -d '{"test": "message"}'
```

4. **Monitor CloudWatch Logs:**
- Check webhook-handler logs for successful SNS publish
- Check background-processor logs for message processing
- Verify idempotency check logs

## Idempotency Implementation

### How It Works

1. **Webhook Handler** generates a unique UUID for each message
2. **Message Published** to SNS with `message_id` in MessageAttributes
3. **Background Processor** receives message and:
   - Extracts `message_id` from SNS attributes
   - Checks database: `SELECT * FROM b2b_pilot_user_submissions WHERE message_id = ?`
   - If exists: Log and skip (return success)
   - If not exists: Process and store with `message_id`

### SNS At-Least-Once Delivery

SNS guarantees **at-least-once delivery**, meaning messages may be delivered multiple times. Our idempotency implementation ensures:

- Duplicate messages are detected via `message_id`
- Database unique constraint prevents duplicate submissions
- Processing is skipped with log entry: `"Message {id} already processed"`

## Cost Comparison

### SQS Costs (Before)
- $0.40 per million requests (polling + processing)
- Continuous polling even when idle
- Estimated: $5-10/month for low volume

### SNS Costs (After)
- $0.50 per million publishes
- $0.00 for Lambda invocations (included in Lambda pricing)
- No idle costs
- Estimated: $2-5/month for low volume (50% savings)

## Monitoring & Alarms

### CloudWatch Metrics to Monitor

1. **SNS:**
   - `NumberOfMessagesPublished`
   - `NumberOfNotificationsFailed`
   - `NumberOfNotificationsDelivered`

2. **Lambda:**
   - `Invocations`
   - `Errors`
   - `Duration`
   - `ConcurrentExecutions`

3. **DLQ:**
   - `ApproximateNumberOfMessagesVisible` (SQS DLQ)

### Alarms Configured

- `SNSFailedDeliveryAlarm` - Alerts on failed SNS → Lambda delivery
- `DLQAlarm` - Alerts when messages enter DLQ
- `ProcessorErrorAlarm` - Alerts on Lambda errors

## Rollback Plan

If issues occur, rollback steps:

1. **Revert code to SQS version:**
```bash
git revert <commit-hash>
sam build && sam deploy
```

2. **No database rollback needed** - `message_id` column is backward compatible (nullable)

3. **Traffic cutover:**
   - Update Twilio webhook URL back to old endpoint if needed
   - SQS queue will automatically resume processing

## Testing

### Unit Tests
```bash
cd lambda-functions
pytest tests/
```

### Integration Tests

1. **Send test message via webhook**
2. **Verify SNS publish in CloudWatch**
3. **Verify Lambda invocation**
4. **Check database for submission with `message_id`**
5. **Send duplicate message (same ID)**
6. **Verify idempotency: No duplicate submission**

### Load Testing

```bash
# Use artillery or similar tool
artillery quick --count 100 --num 10 <webhook-url>
```

Monitor:
- SNS publish rate
- Lambda concurrent executions (should be ≤ 10)
- Error rates
- DLQ messages

## Troubleshooting

### Messages not being processed
- Check SNS subscription status
- Verify Lambda has permission to be invoked by SNS
- Check Lambda logs for errors

### Duplicate submissions despite idempotency
- Verify `message_id` column exists in database
- Check unique index: `idx_user_submissions_message_id`
- Review logs for `message_id` values

### High error rates
- Check Lambda timeout settings (300s)
- Monitor Lambda memory usage
- Review DLQ messages for patterns

### Cost higher than expected
- Check `ReservedConcurrentExecutions` setting
- Monitor invocation count vs. message count
- Look for retry loops

## Best Practices

1. **Always use unique message_id** for each publish
2. **Monitor DLQ regularly** and investigate failures
3. **Set appropriate Lambda reserved concurrency** to control costs
4. **Use SNS message attributes** for filtering (future feature)
5. **Log message_id in all operations** for debugging
6. **Test idempotency regularly** to ensure it works

## Future Enhancements

1. **Multi-subscriber pattern** - Add additional Lambda functions or services
2. **Message filtering** - Use SNS filter policies for routing
3. **Cross-region replication** - SNS supports cross-region delivery
4. **Priority queuing** - Use message attributes + multiple topics

## Support

For issues or questions:
- Check CloudWatch Logs first
- Review this guide
- Contact: [Your team contact]

---

**Migration Date:** [To be filled]  
**Migrated By:** [To be filled]  
**Version:** 2.0.0
