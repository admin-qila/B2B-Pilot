# Local Development Setup

## ✅ Your local stack is now working!

The entire B2B Pilot stack is now running locally using LocalStack.

## Quick Start

### Deploy the stack
```bash
./deploy-local.sh
```

This will:
1. Start LocalStack in Docker
2. Build your Lambda functions
3. Package and upload code to S3
4. Deploy the CloudFormation stack with all resources

### Test the stack
```bash
./test-local.sh
```

## Stack Components

Your local stack includes:

### Lambda Functions
- **webhook-handler** - Receives WhatsApp messages and queues them
- **background-processor** - Processes messages from SQS queue
- **presigned-url** - Generates S3 presigned URLs for file uploads
- **stale-message-processor** - Processes stale messages on a schedule

### SQS Queues
- **b2b-pilot-messages-staging** - Main message queue
- **b2b-pilot-messages-dlq-staging** - Dead letter queue for failed messages

### API Gateway Endpoints
- **POST /authenticity_check** - Webhook endpoint
- **POST /presigned_url** - Generate presigned URLs
- **GET /presigned_url** - Get presigned URL info

## Testing Endpoints

### Get stack outputs
```bash
awslocal cloudformation describe-stacks \
  --stack-name b2b-pilot-local \
  --query 'Stacks[0].Outputs' \
  --output table
```

### Test webhook endpoint
```bash
curl -X POST "http://localhost:4566/restapis/$(awslocal apigateway get-rest-apis --query 'items[0].id' --output text)/staging/_user_request_/authenticity_check" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: dummy" \
  -d '{"Body":"test message","From":"whatsapp:+1234567890"}'
```

### Check SQS messages
```bash
QUEUE_URL=$(awslocal cloudformation describe-stacks --stack-name b2b-pilot-local --query 'Stacks[0].Outputs[?OutputKey==`QueueUrl`].OutputValue' --output text)
awslocal sqs receive-message --queue-url "$QUEUE_URL"
```

### View Lambda logs
```bash
# Webhook handler logs
awslocal logs tail /aws/lambda/b2b-pilot-webhook-handler-staging --follow

# Background processor logs
awslocal logs tail /aws/lambda/b2b-pilot-background-processor-staging --follow
```

### List S3 objects
```bash
awslocal s3 ls s3://test-bucket/
```

### Invoke Lambda directly
```bash
awslocal lambda invoke \
  --function-name b2b-pilot-webhook-handler-staging \
  --payload '{"body": "{\"Body\":\"test\",\"From\":\"whatsapp:+1234567890\"}"}' \
  response.json

cat response.json
```

## Useful Commands

### Restart the stack
```bash
docker compose down
./deploy-local.sh
```

### View LocalStack logs
```bash
docker logs localstack --follow
```

### Stop the stack
```bash
docker compose down
```

### Clean up and redeploy
```bash
docker compose down
rm -rf .aws-sam localstack_data
./deploy-local.sh
```

## Stack Resources

All AWS resources are accessible via:
- **API Gateway**: http://localhost:4566
- **S3**: http://localhost:4566
- **SQS**: http://localhost:4566
- **Lambda**: http://localhost:4566

Use `awslocal` (wrapper for AWS CLI) to interact with LocalStack services.

## Environment Variables

The deployed Lambda functions use these dummy values (configured in `deploy-local.sh`):
- `TWILIO_ACCOUNT_SID=dummy`
- `TWILIO_AUTH_TOKEN=dummy`
- `TWILIO_PHONE_NUMBER=whatsapp:+1234567890`
- `SUPABASE_URL=http://dummy`
- `SUPABASE_KEY=dummy`
- `AI_API_KEY=dummy`
- `VIRUSTOTAL_API_KEY=dummy`
- `GOOGLE_SAFE_BROWSING_KEY=dummy`
- `API_KEY=dummy`

To use real services, update these values in `deploy-local.sh` before deploying.

## Troubleshooting

### LocalStack not starting
```bash
docker compose down
docker compose up -d
docker logs localstack --follow
```

### Functions not deploying
Check Python version matches runtime:
```bash
python3 --version  # Should be 3.12
```

### Can't connect to endpoints
Verify LocalStack is healthy:
```bash
curl http://localhost:4566/_localstack/health | jq .
```
