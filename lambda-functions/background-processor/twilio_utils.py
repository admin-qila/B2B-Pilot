"""
Twilio utilities for webhook validation and message handling
"""
from twilio.request_validator import RequestValidator
from twilio.rest import Client
import logging
import json

logger = logging.getLogger()

def validate_twilio_webhook(auth_token, url, params, signature):
    """
    Validate that a webhook request came from Twilio
    
    Args:
        auth_token: Twilio auth token
        url: The full URL of the webhook endpoint
        params: The POST parameters as a dict
        signature: The X-Twilio-Signature header value
    
    Returns:
        bool: True if valid, False otherwise
    """
    try:
        validator = RequestValidator(auth_token)
        
        # API Gateway might use HTTP internally even if accessed via HTTPS
        # Try HTTPS first, then HTTP if that fails
        if validator.validate(url, params, signature):
            return True
            
        # Try with HTTP if HTTPS failed
        if url.startswith('https://'):
            http_url = url.replace('https://', 'http://', 1)
            if validator.validate(http_url, params, signature):
                logger.info("Webhook validated with HTTP URL conversion")
                return True
        
        logger.warning(f"Failed to validate webhook signature for URL: {url}")
        return False
        
    except Exception as e:
        logger.error(f"Error validating Twilio webhook: {e}")
        return False

def get_twilio_client(account_sid, auth_token):
    """Get authenticated Twilio client"""
    return Client(account_sid, auth_token)

def send_whatsapp_message(client, to_number, from_number, body, media_url=None):
    """
    Send a WhatsApp message via Twilio
    
    Args:
        client: Twilio client instance
        to_number: Recipient's WhatsApp number (format: whatsapp:+1234567890)
        from_number: Your Twilio WhatsApp number (format: whatsapp:+1234567890)
        body: Message body text
        media_url: Optional media URL to include
    
    Returns:
        Message SID if successful, None otherwise
    """
    try:
        # Ensure numbers have whatsapp: prefix
        if not to_number.startswith('whatsapp:'):
            to_number = f'whatsapp:{to_number}'
        if not from_number.startswith('whatsapp:'):
            from_number = f'whatsapp:{from_number}'
        
        kwargs = {
            'body': body,
            'from_': from_number,
            'to': to_number
        }
        
        if media_url:
            kwargs['media_url'] = [media_url]
        
        message = client.messages.create(**kwargs)
        logger.info(f"WhatsApp message sent successfully. SID: {message.sid}")
        return message.sid
        
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return None

def send_whatsapp_message_via_template(client, to_number, from_number, body, media_url=None, submission_id=None, content_sid=None):
    """
    Send a WhatsApp message via Twilio with template support
    
    Args:
        client: Twilio client instance
        to_number: Recipient's WhatsApp number (format: whatsapp:+1234567890)
        from_number: Your Twilio WhatsApp number (format: whatsapp:+1234567890)
        body: Message body text or dict with analysis result
        media_url: Optional media URL to include
        submission_id: Optional submission ID
        content_sid: Optional content template SID
    
    Returns:
        Message SID if successful, None otherwise
    """
    try:
        if isinstance(body, dict):
            # Format analysis result
            logger.info(f"Preparing to send analysis result: {body}")

            analysis = body.get('analysis', None)
            summary = body.get('summary', 'No summary available')
            barcode = body.get('barcode', [])
            receipt = body.get('receipt', {})

            if barcode:
                summary += f"\nBarcode(s) detected: {', '.join(barcode)}\n"

            for k, v in receipt.items():
                if v:
                    summary += f"{k}: {v}\n"

                # Choose emoji based on label
            if analysis:
                emoji = '🚨'
                color = '🔴'
                label = 'Detected as counterfeit.'
            elif analysis is None:
                emoji = '⚠️'
                color = '🟡'
                label = 'Not confirmed as genuine RR Kabel SUPEREX GREEN/Q1 or insufficient evidence (see summary).'
            else:
                emoji = '✅'
                color = '🟢'
                label = 'Confirmed as genuine RR Kabel SUPEREX GREEN/Q1.'

            
            # If we have a content template, use it
            if content_sid:
                try:
                    # Use conversation API with template
                    conversation_sid = get_or_create_conversation(client, to_number, from_number)
                    message = client.conversations.conversations(conversation_sid).messages.create(
                        author="system",
                        content_sid=content_sid,
                        content_variables=json.dumps({
                            "1": emoji,
                            "2": color,
                            "3": label,
                            "4": body.get('sku', ''),
                            "5": body.get('confidence', 'Low'),
                            "6": summary,
                            "7": submission_id,
                            "8": submission_id

                        })
                    )
                    logger.info(f"WhatsApp template message sent successfully. SID: {message.sid}")
                    return message.sid
                except Exception as e:
                    logger.warning(f"Failed to send via template, falling back to regular message: {e}")
            
            # Fallback to regular message
            formatted_body = f"{emoji} **Analysis Result**\n\n**Label:** {label}\n\n**sku:** {body.get('sku', None)}\n\n**Confidence:** {body.get('confidence', 'Low')}\n\n**Summary:** {summary}"
        else:
            formatted_body = str(body)
        
        # Send the message
        return send_whatsapp_message(client, to_number, from_number, formatted_body, media_url)
        
    except Exception as e:
        logger.error(f"Failed to send WhatsApp template message: {e}")
        return None

def get_or_create_conversation(client, to_number, from_number):
    """
    Get or create a Twilio conversation for a participant
    
    Args:
        client: Twilio client instance
        to_number: Recipient's WhatsApp number
        from_number: Your Twilio WhatsApp number
    
    Returns:
        Conversation SID if successful, None otherwise
    """
    try:
        # Format participant phone number
        participant_phone = format_phone_number(to_number)
        
        # Try to find existing conversation with this participant
        conversations = client.conversations.conversations.list(limit=50)
        
        for conv in conversations:
            participants = client.conversations.conversations(conv.sid).participants.list()
            for participant in participants:
                if participant.messaging_binding and participant.messaging_binding.get('address') == f'whatsapp:{participant_phone}':
                    logger.info(f"Found existing conversation: {conv.sid}")
                    return conv.sid
        
        # Create new conversation if none found
        conversation = client.conversations.conversations.create(
            friendly_name=f"WhatsApp conversation with {participant_phone}"
        )
        
        # Add participant to conversation
        client.conversations.conversations(conversation.sid).participants.create(
            messaging_binding={
                'address': f'whatsapp:{participant_phone}',
                'proxy_address': from_number if from_number.startswith('whatsapp:') else f'whatsapp:{from_number}'
            }
        )
        
        logger.info(f"Created new conversation: {conversation.sid}")
        return conversation.sid
        
    except Exception as e:
        logger.error(f"Error getting/creating conversation: {e}")
        return None

def format_phone_number(phone_number):
    """Ensure phone number is in E.164 format"""
    # Remove whatsapp: prefix if present
    if phone_number.startswith('whatsapp:'):
        phone_number = phone_number.replace('whatsapp:', '')
    
    # Add + if not present
    if not phone_number.startswith('+'):
        phone_number = '+' + phone_number
    
    return phone_number
