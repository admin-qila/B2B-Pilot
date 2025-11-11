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
    from config import SNS_TOPIC_ARN, logger, validate_config
    from client_utils import detect_client_type, ClientType
    from message_parser import MessageParser
    from validation_factory import ValidationFactory
    from response_factory import ResponseFactory
    from message_aggregator import get_aggregator
except ImportError as e:
    print(f"Import error: {e}")
    # Fallback to environment variables if config module not found
    SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
    
    # Create basic logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    def validate_config():
        if not SNS_TOPIC_ARN:
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
sns = boto3.client('sns')

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

        # Check if message should be aggregated (WhatsApp with media)
        try:
            aggregator = get_aggregator()
            
            if aggregator.should_aggregate(unified_message):
                # Aggregate WhatsApp media messages
                should_process, aggregated_message, group_key, should_send_message = aggregator.aggregate_message(unified_message)
                
                if not should_process:
                    # Message is waiting for siblings, return success but don't process yet
                    logger.info(f"Message added to group {group_key}, waiting for more messages")
                    if should_send_message:
                        # First message in group - send acknowledgment
                        return ResponseFactory.create_success_response(
                            client_type,
                            message=None,
                            button_text=unified_message.button_text
                        )
                    else:
                        # Duplicate message - return empty 200 response without any message
                        return {
                            'statusCode': 200,
                            'body': ''
                        }
                
                # We have aggregated message ready to process
                logger.info(f"Processing aggregated message from group {group_key}")
                message_to_send = aggregated_message
                is_aggregated_final_message = True
            else:
                # Not aggregating (non-WhatsApp or text-only), process immediately
                message_to_send = unified_message.to_dict()
                is_aggregated_final_message = False
        
        except Exception as e:
            logger.error(f"Error in message aggregation: {e}, processing immediately")
            message_to_send = unified_message.to_dict()
            is_aggregated_final_message = False

        # Send to SNS for near-instant delivery
        try:
            # Create SNS message from unified message (or aggregated message)
            if isinstance(message_to_send, dict):
                # Convert aggregated dict back to UnifiedMessage
                from message_parser import UnifiedMessage
                message_obj = UnifiedMessage.from_dict(message_to_send)
            else:
                message_obj = unified_message
            
            # Generate unique message ID for idempotency
            import uuid
            message_id = str(uuid.uuid4())
            
            # Create message body
            message_body = json.dumps(message_obj.to_dict())
            
            # Create SNS message attributes
            message_attributes = {
                'client_type': {
                    'DataType': 'String',
                    'StringValue': message_obj.client_type
                },
                'phone_number': {
                    'DataType': 'String',
                    'StringValue': message_obj.phone_number
                },
                'message_id': {
                    'DataType': 'String',
                    'StringValue': message_id
                },
                'timestamp': {
                    'DataType': 'String',
                    'StringValue': datetime.utcnow().isoformat()
                }
            }
            
            # Publish to SNS
            response = sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=message_body,
                MessageAttributes=message_attributes,
                Subject=f"Message from {message_obj.client_type}"
            )
            
            logger.info(f"Message published to SNS successfully. MessageId: {response['MessageId']}")
            
            # If this is the final message in an aggregated group, return empty response
            # (the acknowledgment was already sent with the first message)
            if is_aggregated_final_message:
                logger.info("Returning empty response for aggregated final message")
                return {
                    'statusCode': 200,
                    'body': ''
                }
            
            # Return appropriate response based on client type
            success_message = "Your request is being processed" if client_type != ClientType.WHATSAPP else None
            return ResponseFactory.create_success_response(
                client_type, 
                message=success_message,
                button_text=unified_message.button_text
            )
            
        except Exception as e:
            logger.error(f"Failed to publish message to SNS: {e}")
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
