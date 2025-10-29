"""
AWS Lambda function for handling webhooks from multiple clients
This function receives webhooks, validates them, and immediately queues to SQS
Supports: WhatsApp (via Twilio), WebApp, and Mobile clients
"""
import json
import boto3
import logging
import os
import sys
from datetime import datetime

# Add shared module to path
# Try multiple paths for flexibility in deployment
sys.path.append('/opt/python')  # Lambda Layer path
sys.path.append('/opt/shared')  # Shared utilities path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from config import SQS_QUEUE_URL, logger, validate_config
    from client_utils import detect_client_type, ClientType
    from message_parser import MessageParser
    from validation_factory import ValidationFactory
    from response_factory import ResponseFactory
except ImportError as e:
    print(f"Import error: {e}")
    # Fallback to environment variables if config module not found
    SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')
    
    # Create basic logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    def validate_config():
        if not SQS_QUEUE_URL:
            raise ValueError("Missing required environment variables")
    
    # Import fallbacks for shared utilities
    import urllib.parse
    import uuid
    import base64
    from twilio.twiml.messaging_response import MessagingResponse
    from twilio.request_validator import RequestValidator
    
    # Minimal fallback implementations would go here
    class ClientType:
        WHATSAPP = "whatsapp"
        WEBAPP = "webapp"
        MOBILE = "mobile"
        UNKNOWN = "unknown"

# Initialize AWS clients
sqs = boto3.client('sqs')

# Initialize AWS clients
sqs = boto3.client('sqs')

def lambda_handler(event, context):
    """
    Main Lambda handler for multi-client webhooks
    
    Args:
        event: API Gateway event containing webhook data
        context: Lambda context
    
    Returns:
        API Gateway response (TwiML for WhatsApp, JSON for others)
    """
    try:
        # Validate configuration
        validate_config()
        
        # Detect client type from request
        client_type = detect_client_type(event)
        logger.info(f"Detected client type: {client_type.value if hasattr(client_type, 'value') else client_type}")
        
        # Validate request based on client type
        is_valid, validation_error = ValidationFactory.validate_request(event, client_type)
        if not is_valid:
            logger.warning(f"Request validation failed: {validation_error}")
            return ResponseFactory.create_validation_error_response(client_type, validation_error)
        
        # Parse message using unified parser
        try:
            unified_message = MessageParser.parse_message(event, client_type)
        except Exception as e:
            logger.error(f"Failed to parse message: {e}")
            return ResponseFactory.create_error_response(
                client_type, 
                "Failed to parse message", 
                400,
                "PARSE_ERROR"
            )
        
        logger.info(f"Processing message from {unified_message.phone_number} with {len(unified_message.media_items)} media items")
        
        # Check allowlist (primarily for WhatsApp)
        is_allowed, allowlist_error = ValidationFactory.check_allowlist(
            unified_message.phone_number, 
            client_type
        )
        if not is_allowed:
            logger.warning(f"Phone number not in allowlist: {unified_message.phone_number}")
            return ResponseFactory.create_allowlist_error_response(client_type)

        # Send to SQS
        try:
            # Create SQS message from unified message
            sqs_message_data = MessageParser.create_sqs_message(unified_message)
            
            response = sqs.send_message(
                QueueUrl=SQS_QUEUE_URL,
                MessageBody=sqs_message_data['message_body'],
                MessageAttributes=sqs_message_data['message_attributes']
            )
            
            logger.info(f"Message queued successfully. SQS MessageId: {response['MessageId']}")
            
            # Return appropriate response based on client type
            success_message = "Your request is being processed" if client_type != ClientType.WHATSAPP else None
            return ResponseFactory.create_success_response(
                client_type, 
                message=success_message,
                button_text=unified_message.button_text
            )
            
        except Exception as e:
            logger.error(f"Failed to queue message to SQS: {e}")
            # Return success response to avoid retries, but log the error
            return ResponseFactory.create_success_response(
                client_type,
                message="Request received, but there was an issue processing it",
                button_text=unified_message.button_text
            )
        
    except Exception as e:
        logger.error(f"Unexpected error in webhook handler: {e}")
        # Try to determine client type for appropriate error response
        try:
            client_type = detect_client_type(event)
        except:
            client_type = ClientType.UNKNOWN
        
        return ResponseFactory.create_error_response(
            client_type,
            "An unexpected error occurred",
            500,
            "INTERNAL_ERROR"
        )
