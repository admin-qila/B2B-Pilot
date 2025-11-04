# Multi-Image Processing Flow

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          INPUT SOURCES                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  WhatsApp (Twilio)              Non-WhatsApp (webapp/mobile)        │
│  ┌──────────────┐               ┌──────────────┐                   │
│  │ MediaUrl0    │               │ s3_keys: [   │                   │
│  │ MediaUrl1    │     OR        │   "key1",    │                   │
│  │ MediaUrl2    │               │   "key2"     │                   │
│  │ NumMedia: 3  │               │ ]            │                   │
│  └──────────────┘               └──────────────┘                   │
│                                                                       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     HANDLER.PY (process_media_message)              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  1. Limit to max 3 images                                           │
│  2. Loop through each media item                                     │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  For WhatsApp:                                              │   │
│  │    • Download from Twilio URL (with auth)                   │   │
│  │    • Upload to S3 for persistence                           │   │
│  │    • Store: URL + S3 key                                    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  For Non-WhatsApp:                                          │   │
│  │    • Download from S3 bucket                                │   │
│  │    • Store: S3 key only                                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  3. Convert all to base64                                            │
│     downloaded_images = [img1_bytes, img2_bytes, img3_bytes]        │
│     media_base64_list = [base64(img1), base64(img2), base64(img3)]  │
│                                                                       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  PREDICTOR.PY (predict_response)                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  input: ["base64_img1", "base64_img2", "base64_img3"]              │
│                                                                       │
│  1. _process_image_input()                                           │
│     • Detect list of images                                          │
│     • Limit to max 3                                                 │
│                                                                       │
│  2. _process_with_analysis()                                         │
│     • Log: "Processing 3 images"                                     │
│     • Call ImageScamAnalysis tool                                    │
│                                                                       │
│  3. get_openai_image_scam_analysis()                                 │
│     • Build message with all images:                                 │
│       {                                                              │
│         "role": "user",                                              │
│         "content": [                                                 │
│           {"type": "text", "text": "Is there deception..."},        │
│           {"type": "image_url", "image_url": {"url": "data:..."}},  │
│           {"type": "image_url", "image_url": {"url": "data:..."}},  │
│           {"type": "image_url", "image_url": {"url": "data:..."}}   │
│         ]                                                            │
│       }                                                              │
│     • Single API call to OpenAI GPT-5                                │
│                                                                       │
│  4. Extract websites from result                                     │
│  5. Check URL safety if websites found                               │
│                                                                       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    OPENAI GPT-5 MODEL                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Analyzes ALL images together in context                            │
│  • Detects deception patterns across images                         │
│  • Identifies media authenticity                                     │
│  • Extracts websites from all images                                 │
│  • Provides comprehensive analysis                                   │
│                                                                       │
│  Returns JSON:                                                       │
│  {                                                                   │
│    "label": "Likely Deception",                                     │
│    "AI_media_authenticity": "Manipulated",                          │
│    "confidence": "High",                                             │
│    "reason": "...",                                                 │
│    "recommendation": "...",                                          │
│    "extracted_websites": ["url1", "url2"]                           │
│  }                                                                   │
│                                                                       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   MODELS.PY (create_submission)                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Store results in database:                                          │
│                                                                       │
│  Single Image:                                                       │
│  ┌──────────────────────────────────────────────────────┐          │
│  │ image_url: "https://example.com/img.jpg"   (string) │          │
│  │ s3_key: "user/123/img.jpg"                 (string) │          │
│  └──────────────────────────────────────────────────────┘          │
│                                                                       │
│  Multiple Images:                                                    │
│  ┌──────────────────────────────────────────────────────┐          │
│  │ image_url: ["url1", "url2", "url3"]        (array)  │          │
│  │ s3_key: ["key1", "key2", "key3"]           (array)  │          │
│  └──────────────────────────────────────────────────────┘          │
│                                                                       │
│  Database Type: JSONB                                                │
│  • Single → stored as JSON string                                    │
│  • Multiple → stored as JSON array                                   │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow Example

### Example 1: Single WhatsApp Image

```
User sends 1 image via WhatsApp
  ↓
Twilio webhook: NumMedia=1, MediaUrl0="https://api.twilio.com/..."
  ↓
handler.py downloads from Twilio URL
  ↓
handler.py uploads to S3 → "user/+1234/abc123.jpg"
  ↓
Convert to base64: ["iVBORw0KGgo..."]
  ↓
predictor.py: Single image in list
  ↓
OpenAI analyzes: 1 image
  ↓
Database stores:
  image_url: "https://api.twilio.com/..."
  s3_key: "user/+1234/abc123.jpg"
```

### Example 2: Multiple WhatsApp Images

```
User sends 3 images via WhatsApp
  ↓
Twilio webhook: NumMedia=3, MediaUrl0, MediaUrl1, MediaUrl2
  ↓
handler.py downloads all 3 from Twilio URLs
  ↓
handler.py uploads all 3 to S3 → ["key1", "key2", "key3"]
  ↓
Convert to base64: ["base64_1", "base64_2", "base64_3"]
  ↓
predictor.py: List of 3 images
  ↓
OpenAI analyzes: 3 images together
  ↓
Database stores:
  image_url: ["url1", "url2", "url3"]
  s3_key: ["key1", "key2", "key3"]
```

### Example 3: Multiple Non-WhatsApp Images

```
Webapp/mobile uploads 2 images to S3 first
  ↓
API request: {"s3_keys": ["key1", "key2"], "phone_number": "..."}
  ↓
handler.py downloads 2 from S3
  ↓
Convert to base64: ["base64_1", "base64_2"]
  ↓
predictor.py: List of 2 images
  ↓
OpenAI analyzes: 2 images together
  ↓
Database stores:
  image_url: null (or empty)
  s3_key: ["key1", "key2"]
```

## Error Handling Flow

```
3 images requested
  ↓
Download attempts:
  • Image 1: ✅ Success
  • Image 2: ❌ Failed
  • Image 3: ✅ Success
  ↓
Continue with 2 successful images
  ↓
Process normally with available images
  ↓
Store only successful images:
  image_url: ["url1", "url3"]
  s3_key: ["key1", "key3"]
```

## Performance Characteristics

| Metric | Single Image | 2 Images | 3 Images |
|--------|-------------|----------|----------|
| Download Time | ~0.5s | ~1.0s | ~1.5s |
| Base64 Convert | ~0.1s | ~0.2s | ~0.3s |
| OpenAI API Call | ~3-5s | ~5-8s | ~8-12s |
| Total Time | ~4-6s | ~6-10s | ~10-15s |
| Cost (estimate) | 1x | ~1.5x | ~2x |

## Database Storage

```sql
-- Table schema (simplified)
CREATE TABLE b2b_pilot_user_submissions (
    id UUID PRIMARY KEY,
    phone_number TEXT,
    image_url JSONB,      -- Can be string or array
    s3_key JSONB,         -- Can be string or array
    prediction_result JSONB,
    confidence_score FLOAT,
    scam_label TEXT,
    processing_time_ms INTEGER,
    input_text TEXT,
    created_at TIMESTAMP
);
```

## Key Design Decisions

1. **Max 3 Images**: Balance between comprehensiveness and performance
2. **Single API Call**: More cost-effective and provides better context
3. **JSONB Storage**: Flexible schema supporting both single and multiple
4. **Graceful Degradation**: Process available images if some fail
5. **Backward Compatible**: Single images work without changes
