"""
AWS Lambda function for processing messages from multiple clients via SQS
This function performs the heavy processing and sends replies appropriately
Supports: WhatsApp (via Twilio), WebApp, and Mobile clients
"""
import json
import boto3
import logging
import os
import sys
import time
from datetime import datetime
import requests
import base64
import uuid
from datetime import timedelta
from models import get_db, UserSubmission, UsageInfo
from predictor import predict_response, parse_prediction_result, get_openai_text_scam_analysis, parse_openai_text_output
from s3_service import get_s3_service

# Add shared module to path
# Try multiple paths for flexibility in deployment
sys.path.append('/opt/python')  # Lambda Layer path
sys.path.append('/opt/shared')  # Shared utilities path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

try:
    from config import (
        TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER,
        SUPABASE_URL, SUPABASE_KEY, RESPONSE_FEEDBACK_TEMPLATE, logger, validate_config
    )
    from twilio_utils import get_twilio_client, send_whatsapp_message, send_whatsapp_message_via_template, format_phone_number
    from client_utils import ClientType
    from message_parser import UnifiedMessage, MediaItem
    from media_handler import MediaHandler
except ImportError as e:
    print(f"Import error: {e}")
    # Fallback to environment variables if config module not found
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
    RESPONSE_FEEDBACK_TEMPLATE = os.environ.get('RESPONSE_FEEDBACK_TEMPLATE')
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
    S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
    AI_API_KEY = os.environ.get('AI_API_KEY')
    VIRUSTOTAL_API_KEY = os.environ.get('VIRUSTOTAL_API_KEY')
    GOOGLE_SAFE_BROWSING_KEY = os.environ.get('GOOGLE_SAFE_BROWSING_KEY')
    MAX_PROCESSING_TIME_SECONDS = int(os.environ.get('MAX_PROCESSING_TIME_SECONDS', '900'))
    
    # Create basic logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    def validate_config():
        required_vars = [
            TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER,
            SUPABASE_URL, SUPABASE_KEY, RESPONSE_FEEDBACK_TEMPLATE
        ]
        if not all(required_vars):
            raise ValueError("Missing required environment variables")
    
    # Basic Twilio utilities
    from twilio.rest import Client
    
    # Import fallbacks for shared classes
    class ClientType:
        WHATSAPP = "whatsapp"
        WEBAPP = "webapp"
        MOBILE = "mobile"
        UNKNOWN = "unknown"
        
        def __init__(self, value):
            self.value = value
            
        @classmethod
        def from_value(cls, value):
            # Simple fallback enum-like behavior
            instance = cls.__new__(cls)
            instance.value = value
            return instance
    
    # Minimal fallback for UnifiedMessage
    class UnifiedMessage:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
        
        @classmethod
        def from_dict(cls, data):
            return cls(**data)
    
    # Minimal fallback for MediaItem
    class MediaItem:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    # Minimal fallback for MediaHandler
    class MediaHandler:
        @staticmethod
        def download_media(media_item, client_type):
            # Basic fallback implementation
            return False, None, None
        
        @staticmethod
        def upload_to_s3(media_bytes, phone_number, submission_id, content_type):
            return False, None
    
    def get_twilio_client(account_sid, auth_token):
        return Client(account_sid, auth_token)
    
    def send_whatsapp_message(client, to_number, from_number, body):
        try:
            # Ensure WhatsApp prefix
            if not from_number.startswith('whatsapp:'):
                from_number = f'whatsapp:{from_number}'
            
            message = client.messages.create(
                body=body,
                from_=from_number,
                to=to_number
            )
            return message.sid
        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {e}")
            return None
    
    def format_phone_number(phone):
        # Remove whatsapp: prefix for database lookups
        if phone.startswith('whatsapp:'):
            return phone.replace('whatsapp:', '')
        return phone
    
    def send_whatsapp_message_via_template(client, to_number, from_number, body, media_url=None, submission_id=None, content_sid=None):
        """Fallback implementation for template message sending"""
        try:
            # Simple fallback - just send regular message without template
            return send_whatsapp_message(client, to_number, from_number, str(body))
        except Exception as e:
            logger.error(f"Error in fallback template message: {e}")
            return None


# Initialize clients
sqs = boto3.client('sqs')
s3 = boto3.client('s3')

def lambda_handler(event, context):
    """
    Main Lambda handler for SQS message processing from multiple clients
    
    Args:
        event: SQS event containing one or more messages
        context: Lambda context
    
    Returns:
        Dict with processing results
    """
    try:
        # Validate configuration
        validate_config()
        
        # Initialize Twilio client (for WhatsApp responses)
        twilio_client = get_twilio_client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        processed_count = 0
        failed_count = 0
        
        # Process each message from SQS
        for record in event['Records']:
            try:
                # Parse the unified message
                message_body = json.loads(record['body'])
                receipt_handle = record['receiptHandle']
                
                # Convert back to UnifiedMessage object
                unified_message = UnifiedMessage.from_dict(message_body)
                
                logger.info(f"Processing {unified_message.client_type} message ID: {unified_message.message_id}")
                
                # Process the message based on client type
                success = process_unified_message(unified_message, twilio_client, context)
                
                if success:
                    # Delete message from queue on successful processing
                    sqs.delete_message(
                        QueueUrl=record['eventSourceARN'].split(':')[-1],
                        ReceiptHandle=receipt_handle
                    )
                    processed_count += 1
                else:
                    # Message will return to queue for retry
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing individual message: {e}")
                failed_count += 1
                # Don't delete message - let it retry
        
        logger.info(f"Processing complete. Processed: {processed_count}, Failed: {failed_count}")
        
        return {
            'statusCode': 200,
            'processedMessages': processed_count,
            'failedMessages': failed_count
        }
        
    except Exception as e:
        logger.error(f"Fatal error in message processor: {e}")
        raise

def process_unified_message(unified_message: UnifiedMessage, twilio_client, context):
    """
    Process a unified message from any client type
    
    Args:
        unified_message: UnifiedMessage object
        twilio_client: Initialized Twilio client (for WhatsApp responses)
        context: Lambda context for timeout checking
        
    Returns:
        bool: True if processed successfully, False otherwise
    """
    try:
        start_time = time.time()
        # Get client type as string
        client_type_str = unified_message.client_type
        
        logger.info(f"Processing {client_type_str} message from {unified_message.phone_number}")
        
        # Check if we have enough time to process (leave 30 seconds buffer)
        remaining_time = context.get_remaining_time_in_millis() / 1000
        if remaining_time < 30:
            logger.warning("Insufficient time remaining to process message")
            return False
        
        # Handle button feedback (WhatsApp only)
        if client_type_str == "whatsapp" and unified_message.button_text:
            return handle_button_feedback(unified_message)
        
        # Process content based on type
        response_data = None
        if unified_message.media_items:
            # Handle media analysis
            response_data = process_media_message(
                unified_message, client_type_str, remaining_time
            )
        elif unified_message.text_body:
            # Handle text analysis
            response_data = process_text_message_unified(
                unified_message, client_type_str, remaining_time
            )
        else:
            error_message = "Please send an image or text message for analysis."
            if client_type_str == "whatsapp":
                send_whatsapp_message(
                    twilio_client,
                    to_number=unified_message.from_number,
                    from_number=TWILIO_PHONE_NUMBER,
                    body=error_message
                )
            return True
        
        # Send response based on client type
        if response_data:
            success = send_response_by_client_type(
                response_data, unified_message, client_type_str, twilio_client
            )
            return success
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing unified message: {e}")
        
        # Try to send error message based on client type
        try:
            if client_type_str == "whatsapp":
                send_whatsapp_message(
                    twilio_client,
                    to_number=unified_message.from_number,
                    from_number=TWILIO_PHONE_NUMBER,
                    body="Sorry, there was an error processing your request. Please try again later."
                )
            # For webapp/mobile, errors would be handled differently (e.g., database updates, webhooks)
        except:
            pass
        
        return False

def handle_button_feedback(unified_message: UnifiedMessage) -> bool:
    """Handle button feedback for WhatsApp"""
    try:
        logger.info(f"button_payload: {unified_message.button_payload}")
        logger.info(f"button_text: {unified_message.button_text}")
        
        db = get_db()
        submission_id = unified_message.button_payload[:-4]  # strip last 4 chars
        db.update_submission_feedback(submission_id, 3, unified_message.button_text)
        return True
    except Exception as e:
        logger.error(f"Error updating submission feedback: {e}")
        return False

def process_media_message(unified_message, client_type_str, max_processing_time):
    """
    Process media message for scam detection from any client type
    """
    db = get_db()
    if not db:
        return "Sorry, database service is temporarily unavailable. Please try again later."
    
    # Get first media item
    if not unified_message.media_items:
        return "No media found in your message. Please send an image for analysis."
        
    media_item = unified_message.media_items[0]
    
    try:
        # Download media based on client type
        start_time = time.time()
        
        # Handle Twilio WhatsApp calls with media URL
        if client_type_str == "whatsapp" and media_item.url:
            # Download from Twilio URL
            try:
                # Real Twilio media URL - download with authentication
                auth = (os.getenv("TWILIO_ACCOUNT_SID", os.environ.get('TWILIO_ACCOUNT_SID')), 
                       os.getenv("TWILIO_AUTH_TOKEN", os.environ.get('TWILIO_AUTH_TOKEN')))
                response = requests.get(media_item.url, auth=auth, timeout=30)
                response.raise_for_status()
                image_bytes = response.content
                content_type = response.headers.get('content-type', 'image/jpeg')
            except Exception as e:
                logger.error(f"Error downloading media: {e}")
                return "Sorry, there was an error downloading your media. Please try again."
        
        # Handle non-Twilio calls with S3 key (webapp/mobile/other sources)
        elif media_item.s3_key:
            try:
                logger.info(f"Processing non-Twilio media from S3: {media_item.s3_key}")
                logger.info(f"Client type: {client_type_str}, Phone: {unified_message.phone_number}")
                
                # Download from S3
                bucket_name = os.environ.get('S3_BUCKET_NAME')
                if not bucket_name:
                    logger.error("S3_BUCKET_NAME environment variable not set")
                    return "Sorry, there was an error accessing the media storage. Please try again."
                
                logger.info(f"Attempting S3 download - Bucket: {bucket_name}, Key: {media_item.s3_key}")
                response = s3.get_object(Bucket=bucket_name, Key=media_item.s3_key)
                image_bytes = response['Body'].read()
                content_type = response.get('ContentType', media_item.content_type or 'image/jpeg')
                
                logger.info(f"Successfully downloaded {len(image_bytes)} bytes from S3")
                
                # Log additional text if present
                if unified_message.text_body:
                    logger.info(f"Additional text provided: {unified_message.text_body[:100]}...")
                
            except Exception as e:
                logger.error(f"Error downloading media from S3: {e}")
                return "Sorry, there was an error downloading your media. Please try again."
        
        else:
            logger.warning(f"No valid media source for client type {client_type_str}")
            return "Sorry, media processing is temporarily unavailable for this client type."
        
        # Continue with analysis
        try:
            # Convert media bytes to base64 string for predict_response
            media_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # Analyze media
            prediction_result = predict_response(media_base64)
            processing_time = int((time.time() - start_time) * 1000)

            logger.info(f"Prediction result: {prediction_result}")

            # Parse the result
            parsed_result = {}
            if isinstance(prediction_result, dict) and "final_output" in prediction_result:
                final_output_str = prediction_result.get("final_output", "{}")
                try:
                    parsed_result = json.loads(final_output_str)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode failed: {e} | Raw: {final_output_str[:200]}...")
                    parsed_result = {
                        'label': 'Unknown',
                        'confidence': 0,
                        'reason': 'Unable to parse analysis result',
                        'recommendation': 'Please try again later'
                    }
            else:
                parsed_result = {
                    'label': 'Unknown',
                    'confidence': 0,
                    'reason': 'Invalid prediction result',
                    'recommendation': 'Please try again later'
                }
            
            logger.info(f"Parsed result {parsed_result}")

            # Calculate cost
            cost_usd = 0.01
            
            # Handle S3 key storage
            # For non-Twilio calls, use the existing s3_key from media_item
            # For WhatsApp/Twilio calls, upload to S3 and get new s3_key
            s3_key = media_item.s3_key  # Use existing s3_key if available (non-Twilio)
            
            if client_type_str == "whatsapp" and not s3_key:
                # Only upload if it's a WhatsApp call and doesn't already have an s3_key
                try:
                    s3_service = get_s3_service()
                    if s3_service:
                        upload_success, s3_key = s3_service.upload_image(
                            image_data=image_bytes,
                            phone_number=unified_message.phone_number,
                            submission_id=unified_message.message_id,
                            content_type=content_type
                        )
                        if not upload_success:
                            logger.error(f"Failed to upload media to S3 for {unified_message.phone_number}")
                except Exception as e:
                    logger.warning(f"S3 upload failed: {e}")
            
            # Determine original media URL based on client type
            original_media_url = media_item.url if client_type_str == "whatsapp" else None
            
            # Create submission record
            submission = UserSubmission(
                phone_number=unified_message.phone_number,
                image_url=original_media_url,
                s3_key=s3_key,
                prediction_result=parsed_result,
                confidence_score=parsed_result.get('confidence'),
                scam_label=parsed_result.get('label'),
                processing_time_ms=processing_time,
                cost_usd=cost_usd,
                input_text=unified_message.text_body  # Caption/description if any
            )
            
            submission_id = db.create_submission(submission)
            
            return {
                "body": parsed_result,
                "submission_id": submission_id,
                "client_type": client_type_str
            }
        
        except Exception as e:
            logger.error(f"Error in media analysis: {e}")
            return "Sorry, there was an error analyzing your media. Please try again."
        
        # This code would run if MediaHandler was properly imported:
        # success, media_bytes, content_type = MediaHandler.download_media(media_item, client_type_str)
        # if not success:
        #     return "Sorry, there was an error downloading your media. Please try again."
        
        # # Convert media bytes to base64 string for predict_response
        # media_base64 = base64.b64encode(media_bytes).decode('utf-8')
        
        # # Analyze media
        # prediction_result = predict_response(media_base64)
        # processing_time = int((time.time() - start_time) * 1000)

        # logger.info(f"Prediction result: {prediction_result}")

        # # Parse the result
        # parsed_result = {}
        # if isinstance(prediction_result, dict) and "final_output" in prediction_result:
        #     final_output_str = prediction_result.get("final_output", "{}")
        #     try:
        #         parsed_result = json.loads(final_output_str)
        #     except json.JSONDecodeError as e:
        #         logger.error(f"JSON decode failed: {e} | Raw: {final_output_str[:200]}...")
        #         parsed_result = {
        #             'label': 'Unknown',
        #             'confidence': 0,
        #             'reason': 'Unable to parse analysis result',
        #             'recommendation': 'Please try again later'
        #         }
        
        # logger.info(f"Parsed result {parsed_result}")

        # # Calculate cost
        # cost_usd = 0.01
        
        # # Upload to S3 if not already there (for Twilio media)
        # s3_key = media_item.s3_key  # Will be None for Twilio media
        # if not s3_key and client_type_str == ClientType.WHATSAPP:
        #     upload_success, s3_key = MediaHandler.upload_to_s3(
        #         media_bytes, 
        #         unified_message.phone_number, 
        #         unified_message.message_id, 
        #         content_type
        #     )
        #     if not upload_success:
        #         logger.error(f"Failed to upload media to S3 for {unified_message.phone_number}")
        
        # # Determine original media URL based on client type
        # original_media_url = media_item.url if client_type_str == ClientType.WHATSAPP else None
        
        # Create submission record
        submission = UserSubmission(
            phone_number=unified_message.phone_number,
            image_url=original_media_url,
            s3_key=s3_key,
            prediction_result=parsed_result,
            confidence_score=parsed_result.get('confidence'),
            scam_label=parsed_result.get('label'),
            processing_time_ms=processing_time,
            cost_usd=cost_usd,
            input_text=unified_message.text_body  # Caption/description if any
        )
        
        submission_id = db.create_submission(submission)
        
        return {
            "body": parsed_result,
            "submission_id": submission_id,
            "client_type": client_type.value
        }
        
    except Exception as e:
        logger.error(f"Error analyzing media: {e}")
        return "Sorry, there was an error analyzing your media. Please try again."

def process_text_message_unified(unified_message, client_type_str, max_processing_time):
    """
    Process text message for scam detection from any client type
    """
    db = get_db()
    if not db:
        return "Sorry, database service is temporarily unavailable. Please try again later."
    return handle_text_analysis_unified(unified_message, client_type_str, db)


def check_user_consent(phone_number):
    """
    Check user consent in Supabase
    """
    try:
        db = get_db()
        if not db:
            logger.warning("Database not available, allowing request")
            return True
            
        privacy_consent, tos_consent, is_phone_verified = db.check_user_consent(phone_number)
        return privacy_consent and tos_consent and is_phone_verified
    except Exception as e:
        logger.error(f"Error checking user consent: {e}")
        # In case of error, don't block the user
        return True

def check_usage_limits(phone_number):
    """
    Check user usage limits
    """
    try:
        db = get_db()
        if not db:
            logger.warning("Database not available, allowing request")
            return {
                'can_proceed': True,
                'current_count': 0,
                'daily_limit': 10,
                'time_until_reset': timedelta(hours=24)
            }
            
        usage_info = db.check_usage_limit(phone_number)
        
        # Convert UsageInfo object to dictionary format expected by the caller
        return {
            'can_proceed': usage_info.can_proceed,
            'current_count': usage_info.current_count,
            'daily_limit': usage_info.daily_limit,
            'time_until_reset': usage_info.time_until_reset
        }
    except Exception as e:
        logger.error(f"Error checking usage limits: {e}")
        # In case of error, allow the request
        return {
            'can_proceed': True,
            'current_count': 0,
            'daily_limit': 10,
            'time_until_reset': timedelta(hours=24)
        }

def format_analysis_result(parsed_result, current_usage, daily_limit, submission_id):
    """Format the analysis result for WhatsApp"""
    label = parsed_result.get('label', 'Unknown')
    confidence = parsed_result.get('confidence', 'Low')
    reason = parsed_result.get('reason', 'Unable to determine')
    recommendation = parsed_result.get('recommendation', 'Please verify independently')
    website_check = parsed_result.get('website_safety_checks_summary', 'No website check done')
    
    # Choose emoji based on label
    if 'Likely Deception' in label:
        emoji = '🚨'
        color = '🔴'
    elif 'Inconclusive' in label:
        emoji = '⚠️'
        color = '🟡'
    elif 'Likely No Deception' in label:
        emoji = '✅'
        color = '🟢'
    else:
        emoji = '❓'
        color = '⚪'
    
    response = f"""{emoji} **Analysis Result**
    
{color} **Label:** {label}

📊 **Confidence:** {confidence}

💡 **Reason:** {reason}

🔍 **Recommendation:** {recommendation}

🕸️ **Website Safety Checks:** {website_check}

🚨 Thanks for being part of our Alpha Testers, and please provide any feedback to your point of contact"""
    
    return response


def handle_text_analysis_unified(unified_message, client_type_str, db):
    """Handle text content analysis from any client type"""
    try:
        # Analyze text
        start_time = time.time()
        
        # Use predict_response which handles text input
        prediction_result = predict_response(unified_message.text_body)
        processing_time = int((time.time() - start_time) * 1000)
        
        # Extract the actual result from the prediction_result structure
        if isinstance(prediction_result, dict) and 'final_output' in prediction_result:
            try:
                # Parse the final_output string which contains the JSON result
                parsed_result = json.loads(prediction_result['final_output'])
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Failed to parse final_output JSON: {e}")
                parsed_result = {
                    'label': 'Unknown',
                    'confidence': 0,
                    'reason': 'Unable to parse analysis result',
                    'recommendation': 'Please try again later'
                }
        else:
            parsed_result = {
                'label': 'Unknown',
                'confidence': 0,
                'reason': 'Invalid prediction result',
                'recommendation': 'Please try again later'
            }
        
        # Calculate cost (example: $0.005 per text analysis - cheaper than image)
        cost_usd = 0.005
        
        # Create submission record
        submission = UserSubmission(
            phone_number=unified_message.phone_number,
            image_url=None,  # No image for text analysis
            s3_key=None,
            prediction_result=parsed_result,
            confidence_score=parsed_result.get('confidence'),
            scam_label=parsed_result.get('label'),
            processing_time_ms=processing_time,
            cost_usd=cost_usd,
            input_text=unified_message.text_body
        )
        
        submission_id = db.create_submission(submission)
        
        return {
            "body": parsed_result,
            "submission_id": submission_id,
            "client_type": client_type_str
        }
        
    except Exception as e:
        logger.error(f"Error analyzing text: {e}")
        return "Sorry, there was an error analyzing your message. Please try again."

def send_response_by_client_type(response_data, unified_message, client_type_str, twilio_client):
    """Send response based on client type"""
    try:
        if client_type_str == "whatsapp":
            # Send WhatsApp response
            if isinstance(response_data, dict) and "body" in response_data:
                body = response_data["body"]
                submission_id = response_data.get("submission_id")
            else:
                # fallback if response_data is just a string
                body = response_data
                submission_id = None
            
            logger.info(f"RESPONSE_FEEDBACK_TEMPLATE: {RESPONSE_FEEDBACK_TEMPLATE}")
            message_sid = send_whatsapp_message_via_template(
                twilio_client,
                to_number=unified_message.from_number,
                from_number=TWILIO_PHONE_NUMBER,
                body=body,
                submission_id=submission_id,
                content_sid=RESPONSE_FEEDBACK_TEMPLATE
            )
            
            if message_sid:
                logger.info(f"WhatsApp response sent successfully. Message SID: {message_sid}")
                return True
            else:
                logger.error("Failed to send WhatsApp response message")
                return False
        
        elif client_type_str in ["webapp", "mobile"]:
            # For webapp/mobile clients, we would typically:
            # 1. Update the database with the result
            # 2. Send a webhook/notification to the client
            # 3. Or rely on the client to poll for results
            
            # For now, just log the result - you'd implement your notification mechanism here
            logger.info(f"Analysis complete for {client_type_str} client: {getattr(unified_message, 'user_id', 'unknown')}")
            logger.info(f"Result: {response_data}")
            
            # TODO: Implement webhook notification or database update for client polling
            # Example:
            # await notify_client_via_webhook(unified_message.user_id, response_data)
            # or
            # update_user_submission_status(response_data['submission_id'], 'completed', response_data)
            
            return True
        
        else:
            logger.error(f"Unknown client type: {client_type_str}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending response for {client_type_str}: {e}")
        return False
