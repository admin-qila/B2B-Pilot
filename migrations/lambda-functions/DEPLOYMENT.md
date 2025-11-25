# Deployment Guide - Multi-Client Qila Service

## Overview
This guide covers deploying the refactored Qila service that supports multiple client types (WhatsApp, WebApp, and Mobile).

## Prerequisites
- AWS CLI configured with appropriate permissions
- SAM CLI installed
- Python 3.12+ (for local testing)

## Quick Deployment

### Method 1: Using the Deployment Script (Recommended)

```bash
# Navigate to the lambda-functions directory
cd lambda-functions/

# For first-time deployment (guided setup)
./deploy.sh --guided

# For subsequent deployments
./deploy.sh --deploy
```

### Method 2: Manual Deployment

```bash
# 1. Copy shared utilities
cp shared/python/*.py webhook-handler/
cp shared/python/*.py background-processor/
cp shared/python/*.py presigned-url/

# 2. Build
sam build

# 3. Deploy
sam deploy --guided  # First time
sam deploy            # Subsequent times
```

## Configuration Parameters

During guided deployment, you'll be prompted for:

### Required Parameters
- `TwilioAccountSid`: Your Twilio Account SID
- `TwilioAuthToken`: Your Twilio Auth Token  
- `TwilioPhoneNumber`: Your WhatsApp Business number (format: `whatsapp:+1234567890`)
- `ResponseFeedbackTemplate`: Twilio message template SID for responses
- `AiApiKey`: OpenAI API key for analysis
- `VirusTotalApiKey`: VirusTotal API key for URL scanning
- `GoogleSafeBrowsingKey`: Google Safe Browsing API key
- `S3BucketName`: S3 bucket for storing media files

### Optional Parameters
- `Environment`: Deployment environment (`prod` or `staging`, default: `prod`)
- `ApiKey`: API key for webapp/mobile clients (leave empty if not using)
- `SupabaseUrl`: Supabase project URL (if using)
- `SupabaseKey`: Supabase service role key (if using)

## Post-Deployment

### 1. Configure Twilio Webhook
Update your Twilio WhatsApp webhook URL to:
```
https://{api-gateway-url}/prod/sms
```
(The exact URL will be shown in the deployment output)

### 2. Test WhatsApp Integration
Send a test message to your WhatsApp Business number to verify the existing functionality still works.

### 3. Test WebApp/Mobile Integration
```bash
# Example API call for webapp client
curl -X POST https://{api-gateway-url}/prod/sms \
  -H "Content-Type: application/json" \
  -H "X-Client-Type: webapp" \
  -H "Authorization: Bearer your_jwt_token" \
  -d '{
    "phone_number": "+1234567890",
    "text": "Check this suspicious message",
    "user_id": "test_user"
  }'
```

## Directory Structure

```
lambda-functions/
├── webhook-handler/          # Webhook handler Lambda
│   ├── handler.py           # Main handler (refactored)
│   ├── config.py           # Configuration
│   ├── requirements.txt    # Dependencies
│   └── shared files...     # Copied from shared/
├── background-processor/     # Background processor Lambda  
│   ├── handler.py          # Main handler (refactored)
│   ├── models.py           # Database models
│   ├── predictor.py        # AI analysis
│   ├── s3_service.py       # S3 operations
│   ├── twilio_utils.py     # Twilio utilities
│   ├── requirements.txt    # Dependencies
│   └── shared files...     # Copied from shared/
├── shared/                  # Shared utilities
│   └── python/             # Python modules (Lambda layer format)
│       ├── client_utils.py     # Client type detection
│       ├── message_parser.py   # Message parsing
│       ├── validation_factory.py # Request validation
│       ├── response_factory.py  # Response creation
│       └── media_handler.py     # Media processing
├── template.yaml           # SAM template (updated)
├── samconfig.toml          # SAM configuration
├── deploy.sh               # Deployment script
└── DEPLOYMENT.md           # This file
```

## Shared Code Management

The shared utilities are automatically copied to each Lambda function during deployment. This ensures:
- ✅ All dependencies are available at runtime
- ✅ No complex Lambda layer configuration required  
- ✅ Consistent deployment process

**Important**: Always run deployments through the `deploy.sh` script or manually copy shared files before `sam build`.

## Monitoring

After deployment, monitor the following:

### CloudWatch Logs
- `/aws/lambda/qila-webhook-handler-{env}`
- `/aws/lambda/qila-background-processor-{env}`

### Key Metrics
- API Gateway request counts and errors
- Lambda invocation counts and durations  
- SQS queue depth and message processing rates
- Client type distribution (search logs for "Detected client type:")

### Alarms (Pre-configured)
- High queue depth alert
- Dead letter queue messages
- Lambda function errors

## Rollback

If you need to rollback:

```bash
# Deploy previous version
sam deploy --parameter-overrides Environment=prod

# Or use AWS CLI to rollback CloudFormation stack
aws cloudformation cancel-update-stack --stack-name {stack-name}
```

## Troubleshooting

### Import Errors
If you see import errors for shared modules:
1. Ensure `deploy.sh` was used for deployment
2. Verify shared files are copied: `ls webhook-handler/client_utils.py`
3. Rebuild: `sam build`

### API Gateway CORS Issues
For web clients, ensure CORS headers are properly configured in the template.yaml.

### Client Type Detection Issues
Check CloudWatch logs for "Detected client type:" messages to verify detection is working.

## Development Workflow

1. Make changes to shared utilities in `shared/python/`
2. Test locally if needed
3. Deploy using `./deploy.sh --deploy`
4. Monitor CloudWatch logs for issues

## Security Notes

- API keys for webapp/mobile clients should be properly validated
- Consider implementing rate limiting for non-WhatsApp clients  
- Regularly rotate secrets and API keys
- Monitor for unusual client type patterns

---

For questions or issues, refer to the main `REFACTORING_SUMMARY.md` file.