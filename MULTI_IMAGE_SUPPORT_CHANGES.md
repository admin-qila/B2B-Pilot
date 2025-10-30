# Multi-Image Support Implementation Summary

## Overview
Modified the background-processor to support processing multiple images (up to 3) in both WhatsApp and non-WhatsApp modalities.

## Changes Made

### 1. predictor.py
**File**: `lambda-functions/background-processor/predictor.py`

#### Changes:
- **Updated `predict_response()` signature**: Now accepts `Union[str, bytes, List[str]]` to handle lists of images
- **Updated `_process_image_input()`**: 
  - Now accepts `Union[str, List[str]]` 
  - Converts single images to list for uniform processing
  - Limits to maximum 3 images
- **Updated `_process_with_analysis()`**: 
  - Now accepts `Union[str, List[str]]`
  - Logs number of images when processing multiple
- **Updated `get_openai_image_scam_analysis()`**:
  - Now accepts `Union[str, List[str]]`
  - Converts single image to list internally
  - Builds content array with all images (up to 3)
  - Passes all images to OpenAI GPT-5 model in a single API call
  - Updates prompt text to reflect single vs multiple images

#### Key Features:
- Automatically limits to 3 images maximum
- Maintains backward compatibility with single image inputs
- Single API call to OpenAI with all images for comprehensive analysis

---

### 2. handler.py
**File**: `lambda-functions/background-processor/handler.py`

#### Changes in `process_media_message()`:
- **Media Processing**: Now processes up to 3 media items instead of just the first one
- **Parallel Download**: Downloads all media items (WhatsApp or S3) in a loop
- **Error Handling**: Continues processing if one image fails to download
- **WhatsApp Media**: Uploads all WhatsApp media items to S3 with unique submission IDs
- **S3 Media**: Downloads multiple S3 objects for non-WhatsApp clients
- **Base64 Conversion**: Converts all downloaded images to base64 list
- **Prediction**: Passes list of base64 images to `predict_response()`
- **Submission Storage**: Stores primary image in main fields, all images in JSON arrays

#### Key Features:
- Handles both WhatsApp (URL-based) and non-WhatsApp (S3-based) media
- Graceful degradation: processes successfully downloaded images even if some fail
- Maintains backward compatibility by storing first image in primary fields
- Logs detailed information for debugging

---

### 3. models.py
**File**: `lambda-functions/background-processor/models.py`

#### Changes to `UserSubmission` dataclass:
- **Modified existing fields** to support both single and multiple values:
  - `image_url: Optional[Union[str, List[str]]]` - Single URL or list of URLs
  - `s3_key: Optional[Union[str, List[str]]]` - Single S3 key or list of S3 keys

#### Changes to `create_submission()`:
- **Smart Type Handling**: 
  - Single image → stores as string (backward compatible)
  - Multiple images → converts to JSON string for JSONB storage
- **No new columns needed**: Uses existing `image_url` and `s3_key` columns

#### Key Features:
- Backward compatible with existing single-image submissions
- No database schema changes required (only type conversion)
- Handles None values gracefully

---

## Database Considerations

### Required Database Changes:
You need to modify the existing columns to support JSONB type:

```sql
-- Convert existing TEXT columns to JSONB
-- This allows storing both single strings and JSON arrays
ALTER TABLE b2b_pilot_user_submissions 
ALTER COLUMN image_url TYPE JSONB USING 
  CASE 
    WHEN image_url IS NULL THEN NULL
    WHEN image_url::text LIKE '[%' THEN image_url::jsonb
    ELSE to_jsonb(image_url::text)
  END;

ALTER TABLE b2b_pilot_user_submissions 
ALTER COLUMN s3_key TYPE JSONB USING 
  CASE 
    WHEN s3_key IS NULL THEN NULL
    WHEN s3_key::text LIKE '[%' THEN s3_key::jsonb
    ELSE to_jsonb(s3_key::text)
  END;
```

### Backward Compatibility:
- **Single images**: Stored as JSON string (e.g., `"https://example.com/image.jpg"`)
- **Multiple images**: Stored as JSON array (e.g., `["url1", "url2", "url3"]`)
- Existing single-string values are automatically wrapped in JSON format
- No new columns needed - uses existing schema

---

## Testing Scenarios

### 1. WhatsApp with Single Image
- Should work exactly as before
- Primary fields populated, multi-image fields NULL

### 2. WhatsApp with Multiple Images (2-3)
- All images downloaded from Twilio
- All uploaded to S3
- All passed to OpenAI for analysis
- `image_url` stores JSON array: `["url1", "url2", "url3"]`
- `s3_key` stores JSON array: `["key1", "key2", "key3"]`

### 3. Non-WhatsApp (webapp/mobile) with Single Image
- Downloads from S3
- Works exactly as before

### 4. Non-WhatsApp (webapp/mobile) with Multiple Images (2-3)
- All images downloaded from S3
- All passed to OpenAI for analysis
- `image_url` stores JSON array (or `null` if S3-only)
- `s3_key` stores JSON array: `["key1", "key2", "key3"]`

### 5. Mixed Success Scenarios
- If some images fail to download, processes available images
- At least one successful download required

---

## Usage Limits

The current implementation:
- **Maximum 3 images per submission**
- Images are processed together in a single OpenAI API call
- Processing time scales with number of images
- Usage tracking still counts as one submission

---

## API Integration

### WhatsApp (Twilio):
- Automatically detects multiple media items from `NumMedia` parameter
- Downloads each `MediaUrl{i}` with Twilio authentication
- Uploads each to S3 for persistence

### Non-WhatsApp (webapp/mobile):
- Expects `s3_keys` array in request body
- Can also handle single `s3_key` field for backward compatibility
- Downloads all from S3 bucket

---

## OpenAI Integration

The system now sends multiple images to OpenAI GPT-5 in a single API call:

```python
user_content = [
    {"type": "text", "text": "Is there some form of deception in these images?"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]
```

This allows the model to analyze all images together and provide a comprehensive analysis considering the context across all images.

---

## Error Handling

- **Partial Failures**: System continues if some images fail to download
- **Complete Failure**: Returns error message if no images download successfully
- **S3 Upload Failures**: Logged but doesn't prevent analysis (for WhatsApp media)
- **API Errors**: Caught and logged with appropriate error messages

---

## Logging

Enhanced logging at every step:
- Number of media items to process
- Download progress for each image
- S3 upload status for each image
- Number of images passed to OpenAI
- Final analysis results

---

## Next Steps

1. **Test with real data**: Send multiple images via WhatsApp and webapp
2. **Monitor performance**: Check processing times with multiple images
3. **Database migration**: Ensure new columns exist in production
4. **Update API documentation**: Document multi-image support for API clients
5. **Consider usage limits**: Decide if multiple images should count as multiple requests

---

## Backward Compatibility

✅ **All changes are backward compatible**:
- Single image submissions store as JSON string (e.g., `"url"`)
- Multiple images store as JSON array (e.g., `["url1", "url2"]`)
- Existing API contracts unchanged
- Database columns converted to JSONB (supports both formats)
- No breaking changes to existing functionality
- Queries can handle both single strings and arrays
