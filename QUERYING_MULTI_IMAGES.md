# Querying Multi-Image Data

After the JSONB migration, the `image_url` and `s3_key` columns can contain either:
- A single value stored as a JSON string: `"https://example.com/image.jpg"`
- Multiple values stored as a JSON array: `["url1", "url2", "url3"]`

## Common Query Patterns

### 1. Check if submission has multiple images

```sql
-- Check if image_url is an array (multiple images)
SELECT id, phone_number, 
       jsonb_typeof(image_url) as url_type,
       jsonb_typeof(s3_key) as key_type
FROM b2b_pilot_user_submissions
WHERE jsonb_typeof(image_url) = 'array';
```

### 2. Extract single value (backward compatible)

```sql
-- For single image (string type)
SELECT id, image_url #>> '{}' as image_url_string
FROM b2b_pilot_user_submissions
WHERE jsonb_typeof(image_url) = 'string';

-- Alternative: Cast directly
SELECT id, image_url::text as image_url_string
FROM b2b_pilot_user_submissions
WHERE jsonb_typeof(image_url) = 'string';
```

### 3. Extract all images from array

```sql
-- Get all image URLs from an array
SELECT id, 
       jsonb_array_elements_text(image_url) as individual_url
FROM b2b_pilot_user_submissions
WHERE jsonb_typeof(image_url) = 'array';

-- Count number of images per submission
SELECT id, 
       jsonb_array_length(image_url) as num_images
FROM b2b_pilot_user_submissions
WHERE jsonb_typeof(image_url) = 'array';
```

### 4. Handle both single and multiple images

```sql
-- Get first image regardless of type
SELECT id,
       CASE 
         WHEN jsonb_typeof(image_url) = 'string' THEN image_url #>> '{}'
         WHEN jsonb_typeof(image_url) = 'array' THEN image_url -> 0 #>> '{}'
         ELSE NULL
       END as first_image_url
FROM b2b_pilot_user_submissions;
```

### 5. Filter by specific image URL

```sql
-- Find submissions containing a specific URL (works for both single and array)
SELECT id, phone_number, image_url
FROM b2b_pilot_user_submissions
WHERE 
  -- Match single string
  (jsonb_typeof(image_url) = 'string' AND image_url #>> '{}' LIKE '%example.com%')
  OR
  -- Match any element in array
  (jsonb_typeof(image_url) = 'array' AND image_url ? 'https://example.com/specific-image.jpg');
```

### 6. Get submissions with multiple images

```sql
-- Find all submissions with 2 or more images
SELECT id, phone_number, 
       jsonb_array_length(image_url) as num_images,
       image_url
FROM b2b_pilot_user_submissions
WHERE jsonb_typeof(image_url) = 'array' 
  AND jsonb_array_length(image_url) >= 2;
```

### 7. Expand multi-image submissions into rows

```sql
-- Create one row per image (useful for analytics)
SELECT 
    id,
    phone_number,
    CASE 
      WHEN jsonb_typeof(image_url) = 'string' THEN image_url #>> '{}'
      WHEN jsonb_typeof(image_url) = 'array' THEN elem #>> '{}'
      ELSE NULL
    END as image_url,
    CASE 
      WHEN jsonb_typeof(s3_key) = 'string' THEN s3_key #>> '{}'
      WHEN jsonb_typeof(s3_key) = 'array' THEN s3_elem #>> '{}'
      ELSE NULL
    END as s3_key
FROM b2b_pilot_user_submissions
LEFT JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(image_url) = 'array' THEN image_url ELSE '[]'::jsonb END
) elem ON true
LEFT JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(s3_key) = 'array' THEN s3_key ELSE '[]'::jsonb END
) s3_elem ON true;
```

## Python/Application Code Examples

### Reading from database

```python
def get_image_urls(submission_record):
    """Extract image URLs from a submission record."""
    image_url = submission_record.get('image_url')
    
    if image_url is None:
        return []
    elif isinstance(image_url, str):
        # Single image stored as string
        return [image_url]
    elif isinstance(image_url, list):
        # Multiple images stored as array
        return image_url
    else:
        return []

def get_s3_keys(submission_record):
    """Extract S3 keys from a submission record."""
    s3_key = submission_record.get('s3_key')
    
    if s3_key is None:
        return []
    elif isinstance(s3_key, str):
        # Single key stored as string
        return [s3_key]
    elif isinstance(s3_key, list):
        # Multiple keys stored as array
        return s3_key
    else:
        return []
```

### Example usage

```python
from models import get_db

db = get_db()
submission = db.get_submission_by_id('some-id')

# Get all image URLs
image_urls = get_image_urls(submission)
print(f"Submission has {len(image_urls)} image(s)")

# Get all S3 keys
s3_keys = get_s3_keys(submission)

# Iterate through all images
for idx, (url, key) in enumerate(zip(image_urls, s3_keys)):
    print(f"Image {idx + 1}: URL={url}, S3={key}")
```

## Statistics Queries

### Count submissions by image count

```sql
SELECT 
    CASE 
        WHEN image_url IS NULL THEN 'no_image'
        WHEN jsonb_typeof(image_url) = 'string' THEN '1_image'
        WHEN jsonb_array_length(image_url) = 2 THEN '2_images'
        WHEN jsonb_array_length(image_url) = 3 THEN '3_images'
        ELSE 'other'
    END as image_count_category,
    COUNT(*) as submission_count
FROM b2b_pilot_user_submissions
GROUP BY image_count_category
ORDER BY image_count_category;
```

### Average images per submission

```sql
SELECT 
    AVG(
        CASE 
            WHEN jsonb_typeof(image_url) = 'string' THEN 1
            WHEN jsonb_typeof(image_url) = 'array' THEN jsonb_array_length(image_url)
            ELSE 0
        END
    ) as avg_images_per_submission
FROM b2b_pilot_user_submissions
WHERE image_url IS NOT NULL;
```

## Performance Considerations

1. **GIN Indexes**: For frequent queries on JSONB columns, create GIN indexes:
   ```sql
   CREATE INDEX idx_image_url_jsonb ON b2b_pilot_user_submissions USING gin(image_url);
   CREATE INDEX idx_s3_key_jsonb ON b2b_pilot_user_submissions USING gin(s3_key);
   ```

2. **Type Checks**: Cache `jsonb_typeof()` results if using multiple times in same query

3. **Array Operations**: JSONB array operations are efficient but may be slower than simple TEXT comparisons for single values

## Backward Compatibility Notes

- Old code expecting TEXT will need minor updates to handle JSONB
- Single-value queries work with `#>> '{}'` operator to extract string
- Array queries only work for multi-image submissions
- NULL values remain NULL (no changes)
