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
from predictor import predict_response
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
    
    # def send_whatsapp_message_via_template(client, to_number, from_number, body, media_url=None, submission_id=None, content_sid=None):
    #     """Fallback implementation for template message sending"""
    #     try:
    #         # Simple fallback - just send regular message without template
    #         return send_whatsapp_message(client, to_number, from_number, str(body))
    #     except Exception as e:
    #         logger.error(f"Error in fallback template message: {e}")
    #         return None


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
        else:
            error_message = "Please send an image for analysis."
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
    Supports up to 3 images at once
    """
    db = get_db()
    if not db:
        return "Sorry, database service is temporarily unavailable. Please try again later."
    
    # Check for media items
    if not unified_message.media_items:
        return "No media found in your message. Please send an image for analysis."
    
    # Limit to maximum 3 images
    media_items_to_process = unified_message.media_items[:3]
    logger.info(f"Processing {len(media_items_to_process)} media item(s)")
    
    try:
        # Download all media items
        start_time = time.time()
        downloaded_images = []
        s3_keys = []
        original_media_urls = []
        
        for idx, media_item in enumerate(media_items_to_process):
            logger.info(f"Downloading media item {idx + 1}/{len(media_items_to_process)}")
            
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
                    
                    downloaded_images.append(image_bytes)
                    original_media_urls.append(media_item.url)
                    
                    # Upload to S3 for WhatsApp media
                    try:
                        s3_service = get_s3_service()
                        if s3_service:
                            upload_success, s3_key = s3_service.upload_image(
                                image_data=image_bytes,
                                phone_number=unified_message.phone_number,
                                submission_id=f"{unified_message.message_id}_{idx}",
                                content_type=content_type
                            )
                            if upload_success:
                                s3_keys.append(s3_key)
                            else:
                                s3_keys.append(None)
                                logger.error(f"Failed to upload media {idx} to S3")
                        else:
                            s3_keys.append(None)
                    except Exception as e:
                        logger.warning(f"S3 upload failed for media {idx}: {e}")
                        s3_keys.append(None)
                        
                except Exception as e:
                    logger.error(f"Error downloading media {idx}: {e}")
                    # Continue with other images even if one fails
                    continue
            
            # Handle non-Twilio calls with S3 key (webapp/mobile/other sources)
            elif media_item.s3_key:
                try:
                    logger.info(f"Processing non-Twilio media from S3: {media_item.s3_key}")
                    logger.info(f"Client type: {client_type_str}, Phone: {unified_message.phone_number}")
                    
                    # Download from S3
                    bucket_name = os.environ.get('S3_BUCKET_NAME')
                    if not bucket_name:
                        logger.error("S3_BUCKET_NAME environment variable not set")
                        continue
                    
                    logger.info(f"Attempting S3 download - Bucket: {bucket_name}, Key: {media_item.s3_key}")
                    response = s3.get_object(Bucket=bucket_name, Key=media_item.s3_key)
                    image_bytes = response['Body'].read()
                    content_type = response.get('ContentType', media_item.content_type or 'image/jpeg')
                    
                    logger.info(f"Successfully downloaded {len(image_bytes)} bytes from S3")
                    
                    downloaded_images.append(image_bytes)
                    s3_keys.append(media_item.s3_key)
                    original_media_urls.append(None)
                    
                except Exception as e:
                    logger.error(f"Error downloading media {idx} from S3: {e}")
                    continue
            
            else:
                logger.warning(f"No valid media source for media item {idx}, client type {client_type_str}")
                continue
        
        # Check if we downloaded at least one image
        if not downloaded_images:
            return "Sorry, there was an error downloading your media. Please try again."
        
        # Log additional text if present
        if unified_message.text_body:
            logger.info(f"Additional text provided: {unified_message.text_body[:100]}...")
        
        # Continue with analysis
        try:
            # Convert all media bytes to base64 strings for predict_response
            media_base64_list = [base64.b64encode(img_bytes).decode('utf-8') for img_bytes in downloaded_images]
            
            # Analyze media (pass list of base64 images)
            prediction_result = predict_response(media_base64_list)
            processing_time = int((time.time() - start_time) * 1000)

            logger.info(f"Prediction result: {prediction_result}")

            # Filter out None values from S3 keys and URLs
            s3_keys_filtered = [k for k in s3_keys if k is not None]
            original_urls_filtered = [u for u in original_media_urls if u is not None]
            
            # Determine values for image_url and s3_key fields:
            # - Single image: store as string (backward compatible)
            # - Multiple images: store as list (will be converted to JSONB)
            if len(s3_keys_filtered) == 1:
                s3_key_value = s3_keys_filtered[0]
            elif len(s3_keys_filtered) > 1:
                s3_key_value = s3_keys_filtered
            else:
                s3_key_value = None
            
            if len(original_urls_filtered) == 1:
                image_url_value = original_urls_filtered[0]
            elif len(original_urls_filtered) > 1:
                image_url_value = original_urls_filtered
            else:
                image_url_value = None
            
            # Create submission record
            # For single images: stores as string (backward compatible)
            # For multiple images: stores as list which will be converted to JSONB
            submission = UserSubmission(
                phone_number=unified_message.phone_number,
                image_url=image_url_value,
                s3_key=s3_key_value,
                prediction_result=prediction_result,
                confidence_score=prediction_result.get('confidence'),
                scam_label="",
                processing_time_ms=processing_time,
                input_text=unified_message.text_body  # Caption/description if any
            )
            
            submission_id = db.create_submission(submission)
            
            return {
                "body": prediction_result,
                "submission_id": submission_id,
                "client_type": client_type_str
            }
        
        except Exception as e:
            logger.error(f"Error in media analysis: {e}")
            return "Sorry, there was an error analyzing your media. Please try again."   
    
    except Exception as e:
        logger.error(f"Error analyzing media: {e}")
        return "Sorry, there was an error analyzing your media. Please try again."



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
