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
  
NOTE : Copy the shared folder to the Webhook handler and Background Processor folders

## Deployment

### Prerequisites

- AWS CLI configured with appropriate credentials
- SAM CLI installed (`pip install aws-sam-cli`)
- Python 3.11+ installed
