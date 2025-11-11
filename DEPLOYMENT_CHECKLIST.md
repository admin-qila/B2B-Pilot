# SNS Migration Deployment Checklist

## Pre-Deployment

### Database Migration
- [ ] Backup production database
- [ ] Run migration script on staging/dev database first
  ```bash
  psql -h <staging-host> -U <user> -d <database> -f migrations/add_message_id_column.sql
  ```
- [ ] Verify migration success (check for `message_id` column)
- [ ] Run migration script on production database
  ```bash
  psql -h <prod-host> -U <user> -d <database> -f migrations/add_message_id_column.sql
  ```
- [ ] Verify indexes created successfully:
  - `idx_user_submissions_message_id`
  - `idx_user_submissions_message_id_lookup`

### Code Review
- [ ] Review all changes in pull request
- [ ] Verify `template.yaml` SNS configuration
- [ ] Verify Lambda handlers updated for SNS event format
- [ ] Check idempotency implementation in `background-processor`
- [ ] Confirm message_id generation in `webhook-handler`
- [ ] Review error handling and DLQ configuration

### Testing
- [ ] Unit tests pass locally
  ```bash
  cd lambda-functions && pytest
  ```
- [ ] Deploy to staging environment
- [ ] Test webhook endpoint with sample message
- [ ] Verify SNS topic created
- [ ] Verify Lambda subscription to SNS
- [ ] Test idempotency (send duplicate message_id)
- [ ] Test error scenarios (invalid data, timeouts)
- [ ] Check DLQ receives failed messages
- [ ] Load test staging (100+ messages)

## Deployment

### Backup Current State
- [ ] Export current CloudFormation stack
  ```bash
  aws cloudformation get-template \
    --stack-name b2b-pilot-prod \
    --query TemplateBody > backup-stack.json
  ```
- [ ] Note current resource IDs (SQS queue URLs, Lambda ARNs)
- [ ] Document current environment variables

### Build & Deploy
- [ ] Set environment variables
  ```bash
  export AWS_PROFILE=your-profile
  export AWS_REGION=us-east-1
  ```
- [ ] Build SAM application
  ```bash
  cd lambda-functions
  sam build
  ```
- [ ] Validate template
  ```bash
  sam validate
  ```
- [ ] Deploy to production
  ```bash
  sam deploy \
    --guided \
    --stack-name b2b-pilot-prod \
    --capabilities CAPABILITY_IAM
  ```
- [ ] Confirm stack update successful
- [ ] Note new resource ARNs (SNS Topic ARN, Lambda ARNs)

### Configuration Updates
- [ ] Update Twilio webhook URL (if changed)
- [ ] Update any external systems that reference the endpoints
- [ ] Update monitoring dashboards with new metrics

## Post-Deployment Verification

### Infrastructure
- [ ] Verify SNS topic exists
  ```bash
  aws sns list-topics | grep b2b-pilot-messages
  ```
- [ ] Verify Lambda subscription to SNS
  ```bash
  aws sns list-subscriptions-by-topic --topic-arn <topic-arn>
  ```
- [ ] Verify DLQ exists and configured
  ```bash
  aws sqs list-queues | grep dlq
  ```
- [ ] Check Lambda reserved concurrency set to 10
- [ ] Verify IAM permissions for SNS publish

### Functional Testing
- [ ] Send test message via webhook
  ```bash
  curl -X POST <webhook-url> \
    -H "Content-Type: application/json" \
    -d @test-payload.json
  ```
- [ ] Verify message received by Lambda (check logs)
- [ ] Verify message processed successfully
- [ ] Check database for new submission with `message_id`
- [ ] Send duplicate message_id
- [ ] Verify duplicate detected and skipped
- [ ] Test WhatsApp webhook with real message
- [ ] Test webapp client message flow
- [ ] Test stale message processor
  ```bash
  aws lambda invoke \
    --function-name b2b-pilot-stale-message-processor-prod \
    --payload '{}' \
    response.json
  ```

### Monitoring
- [ ] Check CloudWatch Logs for errors
  - webhook-handler logs
  - background-processor logs
  - stale-message-processor logs
- [ ] Verify metrics being published:
  - SNS: NumberOfMessagesPublished
  - Lambda: Invocations, Errors, Duration
  - DLQ: ApproximateNumberOfMessagesVisible
- [ ] Test CloudWatch Alarms
  - SNSFailedDeliveryAlarm
  - DLQAlarm
  - ProcessorErrorAlarm
- [ ] Set up dashboard with key metrics

### Performance Testing
- [ ] Send burst of 50 messages
- [ ] Verify all processed within 1-2 seconds
- [ ] Check concurrent execution count (≤10)
- [ ] Monitor memory usage
- [ ] Check for throttling errors
- [ ] Verify latency < 500ms for most messages

## Monitoring Period (First 24 Hours)

### Hour 1-4
- [ ] Monitor CloudWatch Logs continuously
- [ ] Check error rates every 30 minutes
- [ ] Verify no messages in DLQ
- [ ] Check processing latency
- [ ] Monitor costs in AWS Cost Explorer

### Hour 4-12
- [ ] Check logs every 2 hours
- [ ] Review any errors or warnings
- [ ] Verify idempotency working correctly
- [ ] Check database for duplicate entries (should be none)
- [ ] Monitor SNS metrics

### Hour 12-24
- [ ] Check logs every 4 hours
- [ ] Review full day metrics
- [ ] Compare costs with SQS baseline
- [ ] Document any issues encountered
- [ ] Verify all message types processed correctly

## Rollback Criteria

Rollback if:
- [ ] Error rate > 5%
- [ ] Messages not being processed (> 5 min delay)
- [ ] Duplicate submissions appearing despite idempotency
- [ ] DLQ filling up (> 10 messages)
- [ ] Lambda errors > 10% of invocations
- [ ] Cost spike > 200% of baseline

### Rollback Procedure
If rollback needed:
1. [ ] Identify git commit hash of previous working version
2. [ ] Checkout previous version
   ```bash
   git checkout <previous-commit>
   ```
3. [ ] Deploy previous stack
   ```bash
   sam build && sam deploy
   ```
4. [ ] Update Twilio webhook if needed
5. [ ] Verify SQS processing resumed
6. [ ] Document rollback reason
7. [ ] Schedule post-mortem

## Sign-Off

### Deployment Team
- [ ] Developer: _________________ Date: _______
- [ ] Reviewer: _________________ Date: _______
- [ ] DevOps: ___________________ Date: _______

### Verification
- [ ] All tests passed
- [ ] Monitoring configured
- [ ] Documentation updated
- [ ] Team notified

### Notes
```
[Add any deployment-specific notes, issues encountered, or special configurations]
```

---

**Deployment Date:** _______________  
**Deployed By:** _______________  
**Version:** 2.0.0  
**Stack Name:** b2b-pilot-prod  
**Region:** _______________
