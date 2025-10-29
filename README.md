# Qila WhatsApp Async Processing with AWS Lambda

This directory contains the refactored asynchronous architecture for handling Twilio WhatsApp webhooks using AWS Lambda and SQS.

## Architecture Overview

```
Twilio → API Gateway → Webhook Lambda → SQS Queue → Background Processor Lambda → Twilio REST API
                                              ↓
                                         Dead Letter Queue
```

### Components

1. **Webhook Handler Lambda** (`webhook-handler/`)
   - Receives Twilio webhooks via API Gateway
   - Validates Twilio signatures
   - Immediately queues messages to SQS
   - Returns empty TwiML response within 15 seconds

2. **Background Processor Lambda** (`background-processor/`)
   - Triggered by SQS messages
   - Performs heavy processing (image/text analysis)
   - Sends replies via Twilio REST API
   - Has up to 5 minutes for processing

3. **Shared Layer** (`shared/`)
   - Common utilities for Twilio validation
   - Configuration management
   - Shared dependencies

## Deployment

### Prerequisites

- AWS CLI configured with appropriate credentials
- SAM CLI installed (`pip install aws-sam-cli`)
- Python 3.11+ installed

### Deploy to AWS

1. **Package the shared layer**:
   ```bash
   cd shared
   pip install twilio -t python/
   cd ..
   ```

2. **Build the SAM application**:
   ```bash
   sam build
   ```

3. **Deploy (first time)**:
   ```bash
   sam deploy --guided
   ```
   
   You'll be prompted for:
   - Stack name (e.g., `qila-whatsapp-async`)
   - AWS region
   - Parameter values (Twilio credentials, etc.)
   - Confirm changes

4. **Subsequent deployments**:
   ```bash
   sam deploy
   ```

### Update Twilio Webhook

After deployment, update your Twilio WhatsApp webhook URL:

1. Get the webhook URL from the CloudFormation outputs
2. Log into Twilio Console
3. Navigate to WhatsApp Sandbox or Production number
4. Update the webhook URL to the API Gateway endpoint

## Error Handling & Retry Logic

### Built-in Error Handling

1. **SQS Retry Logic**:
   - Messages are retried up to 3 times automatically
   - Failed messages go to Dead Letter Queue (DLQ) after 3 attempts
   - DLQ messages are retained for 14 days

2. **Lambda Error Handling**:
   - Webhook handler always returns success to avoid Twilio retries
   - Background processor can safely fail and messages will retry
   - Partial batch failures are supported (some messages can fail, others succeed)

3. **Timeout Protection**:
   - Webhook handler: 30 seconds (well under Twilio's 15-second limit)
   - Background processor: 5 minutes
   - SQS visibility timeout: 6 minutes (longer than Lambda timeout)

### Monitoring & Alerts

CloudWatch alarms are configured for:
- High queue depth (>100 messages)
- Messages in DLQ (any message)
- Lambda errors (>5 in 5 minutes)

### Manual Error Recovery

**Process messages from DLQ**:
```python
import boto3
import json

sqs = boto3.client('sqs')
dlq_url = 'your-dlq-url-here'

# Read messages from DLQ
response = sqs.receive_message(
    QueueUrl=dlq_url,
    MaxNumberOfMessages=10
)

for message in response.get('Messages', []):
    body = json.loads(message['Body'])
    print(f"Failed message from {body['from']}: {body['body'][:50]}...")
    
    # Option 1: Re-queue to main queue
    # sqs.send_message(QueueUrl=main_queue_url, MessageBody=message['Body'])
    
    # Option 2: Process manually
    # process_message(body)
    
    # Delete from DLQ when done
    # sqs.delete_message(QueueUrl=dlq_url, ReceiptHandle=message['ReceiptHandle'])
```

## Local Testing

### Test Webhook Handler

```python
# test_webhook.py
import json
import base64
from urllib.parse import urlencode

# Simulate API Gateway event
event = {
    "body": base64.b64encode(urlencode({
        "From": "whatsapp:+1234567890",
        "To": "whatsapp:+0987654321",
        "Body": "Is this message a scam?",
        "NumMedia": "0"
    }).encode()).decode(),
    "isBase64Encoded": True,
    "headers": {
        "X-Twilio-Signature": "test-signature",
        "Host": "api.example.com"
    },
    "path": "/sms"
}

# Test locally (set environment variables first)
from webhook_handler.handler import lambda_handler
response = lambda_handler(event, {})
print(json.dumps(response, indent=2))
```

### Test Background Processor

```python
# test_processor.py
import json

# Simulate SQS event
event = {
    "Records": [{
        "body": json.dumps({
            "messageId": "test-123",
            "from": "whatsapp:+1234567890",
            "body": "Check if this is a scam",
            "numMedia": 0
        }),
        "receiptHandle": "test-handle",
        "eventSourceARN": "arn:aws:sqs:region:account:queue-name"
    }]
}

# Test locally (set environment variables first)
from background_processor.handler import lambda_handler
response = lambda_handler(event, {"get_remaining_time_in_millis": lambda: 300000})
print(json.dumps(response, indent=2))
```

## Environment Variables

Required environment variables for both functions:

```bash
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=whatsapp:+1234567890

# AWS Configuration
SQS_QUEUE_URL=https://sqs.region.amazonaws.com/account/queue-name

# Optional: Supabase Configuration
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

## Best Practices

1. **Idempotency**: Ensure your processing logic is idempotent (can be safely retried)
2. **Logging**: Use structured logging with correlation IDs
3. **Monitoring**: Set up CloudWatch dashboards for queue depth and processing times
4. **Cost Optimization**: Adjust batch sizes and concurrency based on load
5. **Security**: Never log sensitive information (auth tokens, personal data)

## Troubleshooting

### Common Issues

1. **Webhook validation fails**:
   - Check Twilio auth token is correct
   - Verify API Gateway URL matches Twilio configuration
   - Check for HTTP/HTTPS mismatch

2. **Messages stuck in queue**:
   - Check Lambda has correct permissions
   - Verify SQS visibility timeout > Lambda timeout
   - Check for processing errors in CloudWatch logs

3. **High latency**:
   - Increase Lambda memory/concurrency
   - Optimize processing logic
   - Consider using Lambda provisioned concurrency

## Migration from Synchronous

To migrate your existing processing logic:

1. Copy your image/text processing functions to `background-processor/handler.py`
2. Replace the placeholder functions with your actual logic
3. Update database calls to use environment variables
4. Test thoroughly with sample messages
5. Deploy and update Twilio webhook URL

Remember: The webhook handler should do minimal work, just validate and queue!
