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
- **Added new fields**:
  - `all_s3_keys: Optional[List[str]]` - All S3 keys as JSON array
  - `all_image_urls: Optional[List[str]]` - All image URLs as JSON array

#### Changes to `create_submission()`:
- **JSON Serialization**: Converts list fields to JSON strings before storing
- **Conditional Storage**: Only stores multi-image fields if more than one image
- **Backward Compatibility**: Primary `image_url` and `s3_key` still store first image

#### Key Features:
- Backward compatible with existing single-image submissions
- Optional fields for multi-image support
- Handles None values gracefully

---

## Database Considerations

### Required Database Changes (if not already present):
You may need to add the following columns to the `b2b_pilot_user_submissions` table:

```sql
ALTER TABLE b2b_pilot_user_submissions 
ADD COLUMN IF NOT EXISTS all_s3_keys JSONB,
ADD COLUMN IF NOT EXISTS all_image_urls JSONB;
```

### Backward Compatibility:
- Existing single-image submissions continue to work
- Primary fields (`image_url`, `s3_key`) always store the first image
- Multi-image fields are only populated when multiple images are processed

---

## Testing Scenarios

### 1. WhatsApp with Single Image
- Should work exactly as before
- Primary fields populated, multi-image fields NULL

### 2. WhatsApp with Multiple Images (2-3)
- All images downloaded from Twilio
- All uploaded to S3
- All passed to OpenAI for analysis
- First image in primary fields, all in JSON arrays

### 3. Non-WhatsApp (webapp/mobile) with Single Image
- Downloads from S3
- Works exactly as before

### 4. Non-WhatsApp (webapp/mobile) with Multiple Images (2-3)
- All images downloaded from S3
- All passed to OpenAI for analysis
- First image in primary fields, all in JSON arrays

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
- Single image submissions work exactly as before
- Existing API contracts unchanged
- Database schema extended, not modified
- No breaking changes to existing functionality
