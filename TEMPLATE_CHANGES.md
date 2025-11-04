# Template Changes - Stale Message Processor

## Summary
Added the `stale-message-processor` Lambda function to `lambda-functions/template.yaml` for automatic WhatsApp message aggregation cleanup.

---

## Changes Made

### 1. New Lambda Function Resource

**Resource Name:** `StaleMessageProcessorFunction`

**Location:** Lines 204-226 in `template.yaml`

```yaml
StaleMessageProcessorFunction:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: !Sub "b2b-pilot-stale-message-processor-${Environment}"
    CodeUri: stale-message-processor/
    Handler: handler.lambda_handler
    Timeout: 30
    MemorySize: 256
    Environment:
      Variables:
        SQS_QUEUE_URL: !Ref MessageQueue
    Policies:
      - SQSSendMessagePolicy:
          QueueName: !GetAtt MessageQueue.QueueName
    Events:
      ScheduledEvent:
        Type: Schedule
        Properties:
          Schedule: rate(10 seconds)
          Description: Process stale WhatsApp message groups every 10 seconds
          Enabled: true
```

**Features:**
- ✅ Runs every 10 seconds automatically
- ✅ Lower memory (256 MB) for cost efficiency
- ✅ Shorter timeout (30s) since it's a quick check
- ✅ Automatic SQS send permissions
- ✅ Inherits global environment variables (SUPABASE_URL, SUPABASE_KEY, etc.)

---

### 2. New CloudWatch Alarm

**Resource Name:** `StaleProcessorErrorAlarm`

**Location:** Lines 277-291 in `template.yaml`

```yaml
StaleProcessorErrorAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    AlarmName: !Sub "b2b-pilot-stale-processor-errors-${Environment}"
    AlarmDescription: Alert when stale message processor Lambda errors
    MetricName: Errors
    Namespace: AWS/Lambda
    Statistic: Sum
    Period: 300
    EvaluationPeriods: 2
    Threshold: 10
    ComparisonOperator: GreaterThanThreshold
    Dimensions:
      - Name: FunctionName
        Value: !Ref StaleMessageProcessorFunction
```

**Features:**
- ✅ Alerts if more than 10 errors in 10 minutes
- ✅ 2 evaluation periods (handles occasional failures gracefully)
- ✅ Automatically created with stack deployment

---

### 3. New Output

**Output Name:** `StaleMessageProcessorFunction`

**Location:** Lines 306-308 in `template.yaml`

```yaml
StaleMessageProcessorFunction:
  Description: Stale Message Processor Lambda Function ARN
  Value: !GetAtt StaleMessageProcessorFunction.Arn
```

**Purpose:** Provides the Lambda ARN for reference and monitoring

---

## Deployment

### Full Stack Deployment

```bash
cd lambda-functions
sam build
sam deploy --guided
```

This will:
1. Build all Lambda functions including stale-message-processor
2. Create the scheduled CloudWatch Events rule
3. Set up all permissions and alarms
4. Deploy everything together

### Update Existing Stack

If you already have a deployed stack:

```bash
cd lambda-functions
sam build
sam deploy  # Uses existing configuration
```

---

## What Gets Created

When you deploy with SAM, the following resources are automatically created:

1. **Lambda Function**
   - Name: `b2b-pilot-stale-message-processor-prod` (or -staging)
   - Runtime: Python 3.12
   - Memory: 256 MB
   - Timeout: 30 seconds

2. **CloudWatch Events Rule**
   - Schedule: Every 10 seconds
   - Target: StaleMessageProcessorFunction
   - Status: Enabled

3. **IAM Role**
   - SQS send message permissions
   - CloudWatch Logs permissions
   - Lambda execution role

4. **CloudWatch Alarm**
   - Monitors function errors
   - Threshold: 10 errors in 10 minutes

---

## Environment Variables

The function inherits these from `Globals.Function.Environment`:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `RESPONSE_FEEDBACK_TEMPLATE`
- `SUPABASE_URL` ← Used by aggregator
- `SUPABASE_KEY` ← Used by aggregator
- `AI_API_KEY`
- `VIRUSTOTAL_API_KEY`
- `GOOGLE_SAFE_BROWSING_KEY`
- `S3_BUCKET_NAME`
- `API_KEY`
- `SQS_QUEUE_URL` ← Added specifically for this function

---

## Monitoring

### Check Function Status

```bash
aws lambda get-function \
  --function-name b2b-pilot-stale-message-processor-prod
```

### View Logs

```bash
aws logs tail /aws/lambda/b2b-pilot-stale-message-processor-prod --follow
```

### Check Schedule Status

```bash
aws events list-rules \
  --name-prefix StaleMessageProcessorFunctionScheduledEvent
```

### View CloudWatch Alarm

```bash
aws cloudwatch describe-alarms \
  --alarm-names b2b-pilot-stale-processor-errors-prod
```

---

## Cost Implications

### Running Every 10 Seconds

- **Invocations per day:** 8,640 (24 hours × 60 min × 6 per min)
- **Invocations per month:** ~259,200

### AWS Lambda Free Tier

- **Free invocations:** 1,000,000 per month
- **Free compute:** 400,000 GB-seconds per month

### Estimated Cost (after free tier)

With 256 MB and 30s timeout:
- **Memory:** 0.256 GB
- **Compute per invocation:** 0.256 GB × 0.1s (avg) = 0.0256 GB-seconds
- **Monthly compute:** 259,200 × 0.0256 = 6,635.5 GB-seconds

**Cost breakdown:**
- Invocations: $0 (under free tier)
- Compute: $0 (under free tier)
- CloudWatch Logs: ~$0.50/month (minimal logging)

**Total:** ~$0.50 - $1.00 per month

---

## Rollback

If you need to remove the stale-message-processor:

### Option 1: Disable in template

```yaml
# In template.yaml, change:
Enabled: true
# To:
Enabled: false
```

Then redeploy:
```bash
sam deploy
```

### Option 2: Remove from template

Delete the entire `StaleMessageProcessorFunction` resource and alarm, then redeploy.

### Option 3: Manual cleanup

```bash
# Delete CloudWatch rule
aws events remove-targets \
  --rule StaleMessageProcessorFunctionScheduledEvent \
  --ids "1"

aws events delete-rule \
  --name StaleMessageProcessorFunctionScheduledEvent

# Delete Lambda function
aws lambda delete-function \
  --function-name b2b-pilot-stale-message-processor-prod
```

---

## Verification

After deployment, verify everything is working:

### 1. Check function exists
```bash
aws lambda list-functions | grep stale-message-processor
```

### 2. Invoke manually
```bash
aws lambda invoke \
  --function-name b2b-pilot-stale-message-processor-prod \
  response.json

cat response.json
# Should see: {"statusCode": 200, "body": "{\"processed\": 0, ..."}
```

### 3. Check CloudWatch Events
```bash
aws events list-targets-by-rule \
  --rule StaleMessageProcessorFunctionScheduledEvent
```

### 4. Monitor logs
```bash
aws logs tail /aws/lambda/b2b-pilot-stale-message-processor-prod --follow
```

You should see logs every 10 seconds like:
```
Starting stale message processor
No stale messages to process
```

---

## Troubleshooting

### Function not running on schedule

**Check:**
```bash
aws events describe-rule --name StaleMessageProcessorFunctionScheduledEvent
```

**Fix:** Ensure `State: ENABLED` in the output

### Permission errors

**Check IAM role:**
```bash
aws lambda get-function-configuration \
  --function-name b2b-pilot-stale-message-processor-prod \
  --query 'Role'
```

**Fix:** Redeploy with SAM to recreate IAM role

### Supabase connection errors

**Check environment variables:**
```bash
aws lambda get-function-configuration \
  --function-name b2b-pilot-stale-message-processor-prod \
  --query 'Environment'
```

**Fix:** Ensure SUPABASE_URL and SUPABASE_KEY are set

---

## Best Practices

1. **Monitor the function** - Check CloudWatch Logs regularly
2. **Review alarms** - Configure SNS topics for alarm notifications
3. **Tune the schedule** - Adjust from 10s to 30s if traffic is low
4. **Check costs** - Monitor Lambda billing monthly
5. **Test after deployment** - Always invoke manually first

---

## Related Files

- `lambda-functions/template.yaml` - SAM template (modified)
- `lambda-functions/stale-message-processor/handler.py` - Function code
- `lambda-functions/stale-message-processor/requirements.txt` - Dependencies
- `lambda-functions/webhook-handler/message_aggregator.py` - Aggregation logic
- `WHATSAPP_AGGREGATION_GUIDE.md` - Full documentation
- `WHATSAPP_AGGREGATION_CHECKLIST.md` - Setup guide
