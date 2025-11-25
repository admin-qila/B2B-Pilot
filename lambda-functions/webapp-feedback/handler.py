"""
AWS Lambda function for handling webapp feedback
Updates the b2b_pilot_user_submissions table with user feedback
"""
import json
import os
import logging
from datetime import datetime
from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Supabase client
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'prod')

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("Missing required environment variables: SUPABASE_URL or SUPABASE_KEY")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_table_name(base_name: str) -> str:
    """Get the appropriate table name based on environment"""
    if ENVIRONMENT == "staging":
        return f"{base_name}_staging"
    return base_name


def lambda_handler(event, context):
    """
    Main Lambda handler for webapp feedback
    
    Expected JSON body:
    {
        "phone_number": "+16504557855",  # Required
        "rating": "thumbs_up",            # Required: "thumbs_up" or "thumbs_down"
        "comment": "optional comment",    # Optional
        "response_text": "...",           # Optional
        "user_query": "...",              # Optional
        "timestamp": "2025-11-13T19:17:24.133Z"  # Optional
    }
    
    Returns:
        API Gateway response with success/error status
    """
    try:
        # Parse request body
        if 'body' in event:
            if isinstance(event['body'], str):
                body = json.loads(event['body'])
            else:
                body = event['body']
        else:
            body = event
        
        logger.info(f"Received feedback request: {json.dumps(body, default=str)}")
        
        # Validate required fields
        phone_number = body.get('phone_number')
        rating = body.get('rating')
        
        if not phone_number:
            logger.warning("Missing phone_number in request")
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': False,
                    'error': 'phone_number is required'
                })
            }
        
        if not rating:
            logger.warning("Missing rating in request")
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': False,
                    'error': 'rating is required'
                })
            }
        
        # Validate rating value
        if rating not in ['thumbs_up', 'thumbs_down']:
            logger.warning(f"Invalid rating value: {rating}")
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': False,
                    'error': 'rating must be either "thumbs_up" or "thumbs_down"'
                })
            }
        
        # Check if Supabase is initialized
        if not supabase:
            logger.error("Supabase client not initialized")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': False,
                    'error': 'Database connection not available'
                })
            }
        
        # Get optional fields
        comment = body.get('comment', '')
        response_text = body.get('response_text')
        user_query = body.get('user_query')
        timestamp = body.get('timestamp')
        
        # Build feedback text: rating + comment (if provided)
        feedback_text = rating
        if comment:
            feedback_text = f"{rating}: {comment}"
        
        # Find the most recent submission for this phone number
        # We'll update the latest record that doesn't have feedback yet
        try:
            logger.info(f"Searching for recent submission for phone: {phone_number}")
            
            result = supabase.table(get_table_name('b2b_pilot_user_submissions')) \
                .select('id, created_at, feedback_text') \
                .eq('phone_number', phone_number) \
                .is_('feedback_text', 'null') \
                .order('created_at', desc=True) \
                .limit(1) \
                .execute()
            
            if not result.data or len(result.data) == 0:
                logger.warning(f"No recent submission found for phone: {phone_number}")
                return {
                    'statusCode': 404,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'success': False,
                        'error': 'No recent submission found for this phone number without feedback'
                    })
                }
            
            submission_id = result.data[0]['id']
            logger.info(f"Found submission ID: {submission_id}")
            
            # Update the submission with feedback
            update_result = supabase.table(get_table_name('b2b_pilot_user_submissions')) \
                .update({
                    'feedback_text': feedback_text,
                    'updated_at': timestamp or datetime.utcnow().isoformat()
                }) \
                .eq('id', submission_id) \
                .execute()
            
            logger.info(f"Successfully updated submission {submission_id} with feedback")
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': True,
                    'message': 'Feedback saved successfully',
                    'submission_id': submission_id
                })
            }
            
        except Exception as db_error:
            logger.error(f"Database error: {str(db_error)}")
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': False,
                    'error': f'Database error: {str(db_error)}'
                })
            }
    
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': False,
                'error': 'Invalid JSON in request body'
            })
        }
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            })
        }
