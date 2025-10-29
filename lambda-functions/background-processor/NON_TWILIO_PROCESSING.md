# Non-Twilio Call Processing Implementation

## Overview
This document describes the implementation of processing non-Twilio calls in the background-processor Lambda function. Non-Twilio calls include submissions from webapp, mobile apps, or any other sources that upload media directly to S3.

## Changes Made

### 1. Enhanced Media Processing (`handler.py`)

#### Updated `process_media_message()` function:
- Added support for processing media that's already uploaded to S3 via `s3_key`
- Downloads images from S3 bucket when `media_item.s3_key` is present
- Preserves existing Twilio WhatsApp functionality (downloads from Twilio URLs)

**Key logic:**
```python
# Handle Twilio WhatsApp calls with media URL
if client_type_str == "whatsapp" and media_item.url:
    # Download from Twilio URL with authentication
    
# Handle non-Twilio calls with S3 key (webapp/mobile/other sources)
elif media_item.s3_key:
    # Download from S3 bucket using the provided s3_key
```

#### Updated S3 Key Storage Logic:
- For non-Twilio calls: Uses the existing `s3_key` from the incoming message (media already in S3)
- For Twilio calls: Uploads to S3 and generates a new `s3_key` (media downloaded from Twilio)

**Key logic:**
```python
# Use existing s3_key if available (non-Twilio)
s3_key = media_item.s3_key

# Only upload if it's a WhatsApp call and doesn't already have an s3_key
if client_type_str == "whatsapp" and not s3_key:
    # Upload to S3 and get new s3_key
```

#### Enhanced Logging:
- Logs S3 key being processed
- Logs client type and phone number
- Logs additional text if provided
- Logs successful download size

### 2. Message Parser Updates (`message_parser.py`)

#### Added support for `additionalText` field:
The `_parse_json_message()` function now extracts text from multiple possible field names:
- `text`
- `message`  
- `additionalText` (newly added)

**Implementation:**
```python
# Extract text body - check multiple possible field names
text_body = data.get('text', data.get('message', data.get('additionalText', '')))
```

This ensures that any additional text/context provided with the image is captured and stored in the `input_text` field of the submission record.

## API Contract for Non-Twilio Calls

### Required Fields:
- `s3_key`: The S3 object key of the uploaded image
- `phone_number`: User's phone number in E.164 format

### Optional Fields:
- `additionalText` (or `text` or `message`): Additional context about the image
- `message_id`: Unique message identifier (generated if not provided)
- `timestamp`: ISO format timestamp (current time if not provided)
- `user_id`: User identifier for webapp/mobile clients
- `session_id`: Session identifier for webapp/mobile clients
- `content_type`: MIME type of the media (defaults to 'image/jpeg')

### Example JSON Payload:
```json
{
  "s3_key": "images/abc123/2025/01/23/20250123_160156_789_submission123.jpg",
  "phone_number": "+1234567890",
  "additionalText": "Is this email legitimate?",
  "user_id": "user_123",
  "client_type": "webapp"
}
```

## Processing Flow

1. **Message Reception**: Non-Twilio call arrives via API Gateway
2. **Message Parsing**: `MessageParser._parse_json_message()` extracts:
   - S3 key from `s3_key` field
   - Phone number from `phone_number` field
   - Additional text from `additionalText`/`text`/`message` fields
   - Creates `MediaItem` with `s3_key` populated
3. **SQS Queueing**: Message sent to SQS queue for background processing
4. **Background Processing**: 
   - Lambda handler receives message from SQS
   - `process_media_message()` detects `s3_key` in media item
   - Downloads image from S3 bucket
   - Analyzes image using AI model
   - Stores result in database with:
     - Original `s3_key` (no re-upload needed)
     - `input_text` containing the additionalText
     - Analysis results and metadata
5. **Response**: Results sent to client based on client type

## Database Storage

The submission record stores:
- `s3_key`: The S3 location of the image (from input, not re-uploaded)
- `phone_number`: User's phone number
- `input_text`: The additionalText field (if provided)
- `prediction_result`: AI analysis results
- `confidence_score`: Confidence level
- `scam_label`: Detected scam label
- `processing_time_ms`: Processing duration
- `cost_usd`: Processing cost
- `image_url`: NULL for non-Twilio calls (only Twilio has media URLs)

## Benefits

1. **Efficiency**: No need to re-upload images that are already in S3
2. **Consistency**: Same processing pipeline for all client types
3. **Flexibility**: Supports multiple text field names for backwards compatibility
4. **Debugging**: Enhanced logging for troubleshooting
5. **Scalability**: Can handle submissions from any source that uploads to S3

## Testing Recommendations

1. **Unit Tests**:
   - Test message parsing with `s3_key` field
   - Test message parsing with different text field names
   - Test S3 download logic

2. **Integration Tests**:
   - Submit a test message with valid `s3_key`
   - Verify image is downloaded from S3
   - Verify analysis completes successfully
   - Verify submission record is created correctly

3. **End-to-End Tests**:
   - Upload image to S3 via separate upload endpoint
   - Submit processing request with `s3_key` and `additionalText`
   - Verify complete processing flow
   - Verify results are stored and retrievable

## Error Handling

The implementation includes comprehensive error handling:
- Missing S3 bucket configuration
- S3 download failures
- Invalid s3_key
- Processing errors
- Database errors

All errors are logged with context and appropriate error messages are returned to the client.

## Future Enhancements

1. **Validation**: Add validation for s3_key format and existence
2. **Content Type Detection**: Automatically detect content type from S3 metadata
3. **Batch Processing**: Support multiple images in a single request
4. **Cost Optimization**: Implement caching for frequently analyzed images
5. **Security**: Add signature verification for non-Twilio requests
