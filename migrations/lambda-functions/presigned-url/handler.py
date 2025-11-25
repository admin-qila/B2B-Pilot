"""
AWS Lambda function for generating presigned URLs for S3 uploads
This function creates presigned URLs with the existing S3 key structure
"""
import json
import os
import sys
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

# Add shared module to path
sys.path.append('/opt/python')  # Lambda Layer path
sys.path.append('/opt/shared')  # Shared utilities path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    # Import from local directory
    from s3_service import S3Service
    from client_utils import detect_client_type, ClientType
    from validation_factory import ValidationFactory
    from response_factory import ResponseFactory
except ImportError as e:
    logger.error(f"Import error: {e}")
    # Fallback implementation would go here if needed
    S3Service = None
    ValidationFactory = None
    ResponseFactory = None
    
    # Fallback ClientType if needed
    try:
        from client_utils import ClientType
    except ImportError:
        class ClientType:
            WHATSAPP = "whatsapp"
            WEBAPP = "webapp"
            MOBILE = "mobile"
            UNKNOWN = "unknown"
    
    def detect_client_type(event):
        return ClientType.WEBAPP  # Default fallback

def lambda_handler(event, context) -> Dict[str, Any]:
    """
    Main Lambda handler for generating presigned URLs
    
    Args:
        event: API Gateway event containing request data
        context: Lambda context
    
    Returns:
        API Gateway response with presigned URL and S3 key
    """
    try:
        logger.info("Processing presigned URL request")

            # Handle preflight CORS request
        if event["httpMethod"] == "OPTIONS":
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key"
                },
                "body": ""
            }

         # Detect client type from request
        client_type = detect_client_type(event)
        logger.info(f"Detected client type: {client_type.value if hasattr(client_type, 'value') else client_type}")

        is_valid, validation_error = ValidationFactory.validate_request(event, client_type)
        if not is_valid:
            logger.warning(f"Request validation failed: {validation_error}")
            return ResponseFactory.create_validation_error_response(client_type, validation_error)
        

        # Handle both API Gateway events and direct Lambda invocations
        http_method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method', 'GET'))
        
        # Parse request body based on method and event structure
        if http_method == 'POST' and 'body' in event and event['body']:
            try:
                if isinstance(event['body'], str):
                    body = json.loads(event['body'])
                else:
                    body = event['body']
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in request body: {e}")
                return create_error_response(400, "Invalid JSON in request body")
        else:
            # Handle GET request, query parameters, or direct invocation
            body = event.get('queryStringParameters', {}) or {}
            # If no query parameters, check if the entire event is the data
            if not body and 'phone_number' in event:
                body = event
        
        # Extract required parameters
        phone_number = body.get('phone_number')
        submission_id = body.get('submission_id')
        content_type = body.get('content_type', 'image/jpeg')
        expires_in = int(body.get('expires_in', 3600))  # Default 1 hour
        
        # Validate required parameters
        if not phone_number:
            return create_error_response(400, "phone_number is required")
        
        if not submission_id:
            # Generate a submission ID if not provided
            submission_id = str(uuid.uuid4())
        
        # Initialize S3 service
        if not S3Service:
            logger.error("S3Service not available")
            return create_error_response(500, "S3 service not available")
        
        try:
            s3_service = S3Service()
        except Exception as e:
            logger.error(f"Failed to initialize S3Service: {e}")
            return create_error_response(500, f"Failed to initialize S3 service: {str(e)}")
        
        # Generate S3 key using the existing structure
        try:
            s3_key = s3_service.generate_secure_key(phone_number, submission_id)
            logger.info(f"Generated S3 key: {s3_key}")
        except Exception as e:
            logger.error(f"Failed to generate S3 key: {e}")
            return create_error_response(500, f"Failed to generate S3 key: {str(e)}")
        
        # Create presigned URL
        try:
            presigned_response = s3_service.create_presigned_upload_url(
                s3_key=s3_key,
                content_type=content_type,
                expires_in=expires_in
            )
            
            logger.info("Successfully generated presigned URL")
            
            # Return both presigned URL data and the S3 key
            response_data = {
                'presigned_url': presigned_response['url'],
                'fields': presigned_response['fields'],
                's3_key': s3_key,
                'submission_id': submission_id,
                'expires_in': expires_in,
                'content_type': content_type
            }
            
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Api-Key',
                    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
                },
                'body': json.dumps(response_data)
            }
            
        except Exception as e:
            logger.error(f"Failed to create presigned URL: {e}")
            return create_error_response(500, f"Failed to create presigned URL: {str(e)}")
        
    except Exception as e:
        logger.error(f"Unexpected error in presigned URL handler: {e}")
        return create_error_response(500, "An unexpected error occurred")

def create_error_response(status_code: int, message: str) -> Dict[str, Any]:
    """
    Create a standardized error response
    
    Args:
        status_code: HTTP status code
        message: Error message
    
    Returns:
        API Gateway error response
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Api-Key',
            'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
        },
        'body': json.dumps({
            'error': message,
            'timestamp': datetime.utcnow().isoformat()
        })
    }