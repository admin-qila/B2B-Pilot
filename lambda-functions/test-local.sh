#!/bin/bash
set -e

echo "🧪 Testing Local B2B Pilot Stack"
echo "================================="
echo ""

# Get stack outputs
echo "📋 Stack Outputs:"
API_ID=$(awslocal apigateway get-rest-apis --query 'items[0].id' --output text)
QUEUE_URL=$(awslocal cloudformation describe-stacks --stack-name b2b-pilot-local --query 'Stacks[0].Outputs[?OutputKey==`QueueUrl`].OutputValue' --output text)

# Construct LocalStack URLs
WEBHOOK_URL="http://localhost:4566/restapis/${API_ID}/staging/_user_request_/authenticity_check"
PRESIGNED_URL="http://localhost:4566/restapis/${API_ID}/staging/_user_request_/presigned_url"

echo "  API Gateway ID: $API_ID"
echo "  Webhook URL: $WEBHOOK_URL"
echo "  Presigned URL Endpoint: $PRESIGNED_URL"
echo "  Queue URL: $QUEUE_URL"
echo ""

# Test 1: Check Lambda functions
echo "✅ Lambda Functions:"
awslocal lambda list-functions --query 'Functions[*].[FunctionName,Runtime,Handler]' --output table
echo ""

# Test 2: Check SQS queues
echo "✅ SQS Queues:"
awslocal sqs list-queues --query 'QueueUrls[*]' --output table
echo ""

# Test 3: Test webhook endpoint
echo "🔍 Testing webhook endpoint..."
RESPONSE=$(curl -s -X POST "$WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"Body":"test message","From":"whatsapp:+1234567890"}' \
  -w "\nHTTP_STATUS:%{http_code}")

HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_STATUS")

if [ "$HTTP_STATUS" == "200" ] || [ "$HTTP_STATUS" == "202" ]; then
    echo "  ✅ Webhook responded with status $HTTP_STATUS"
    echo "  Response: $BODY"
else
    echo "  ⚠️  Webhook responded with status $HTTP_STATUS"
    echo "  Response: $BODY"
fi
echo ""

# Test 4: Check messages in queue
echo "🔍 Checking SQS queue for messages..."
MSG_COUNT=$(awslocal sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

echo "  Messages in queue: $MSG_COUNT"
echo ""

# Test 5: Test presigned URL endpoint
echo "🔍 Testing presigned URL endpoint..."
PRESIGNED_RESPONSE=$(curl -s -X POST "$PRESIGNED_URL" \
  -H "Content-Type: application/json" \
  -d '{"filename":"test.jpg","content_type":"image/jpeg"}' \
  -w "\nHTTP_STATUS:%{http_code}")

PRESIGNED_HTTP_STATUS=$(echo "$PRESIGNED_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
PRESIGNED_BODY=$(echo "$PRESIGNED_RESPONSE" | grep -v "HTTP_STATUS")

if [ "$PRESIGNED_HTTP_STATUS" == "200" ]; then
    echo "  ✅ Presigned URL endpoint responded with status $PRESIGNED_HTTP_STATUS"
    echo "  Response: $PRESIGNED_BODY"
else
    echo "  ⚠️  Presigned URL endpoint responded with status $PRESIGNED_HTTP_STATUS"
    echo "  Response: $PRESIGNED_BODY"
fi
echo ""

echo "================================="
echo "✅ Local stack testing complete!"
echo ""
echo "💡 Tips:"
echo "  - View Lambda logs: awslocal logs tail /aws/lambda/b2b-pilot-webhook-handler-staging --follow"
echo "  - View queue messages: awslocal sqs receive-message --queue-url $QUEUE_URL"
echo "  - View S3 objects: awslocal s3 ls s3://test-bucket/"
echo "  - Stop stack: docker compose down"
