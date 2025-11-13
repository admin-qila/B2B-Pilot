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
            logger.info(f"to_number: {to_number}")
            logger.info(f"from_number: {from_number}")

            analysis = body.get('analysis', None)
            summary = body.get('summary', 'No summary available') or 'No summary available'
            barcode = body.get('barcodes', []) or []
            receipt = body.get('receipt', {}) or {}
            sku = body.get('sku', '') or ''
            confidence = body.get('confidence', 'low') or 'low'

            if barcode:
                summary += f"\n*Barcode(s) Detected*:"
                for code in barcode:
                    summary += f"\n- Code Type : {code['type']} | Value : {code['data']}"
            summary += "\n"
            for k, v in receipt.items():
                if v:
                    if k == "shop_name":
                        summary += f"*Shop Name*: {v}\n"
                    elif k == "location":
                        summary += f"*Shop Location*: {v}\n"

                # Choose emoji based on label
            if analysis == 'true':
                emoji = '🚨'
                color = '🔴'
                label = 'Counterfeit.'
            elif analysis == 'false':
                emoji = '✅'
                color = '🟢'
                label = 'Genuine'
            else:
                emoji = '⚠️'
                color = '🟡'
                label = 'Insufficient evidence (see summary).'

            
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
                            "4": sku,
                            "5": confidence,
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

def _generate_conversation_unique_name(proxy_address, address):
    """
    Generate a unique name for a conversation based on proxy_address and address.
    Format: conv_{proxy_address}_{address}
    
    Args:
        proxy_address: The Twilio WhatsApp number (proxy_address)
        address: The recipient's WhatsApp number (address)
    
    Returns:
        Unique name string
    """
    return f"conv_{proxy_address}_{address}"

def get_or_create_conversation(client, to_number, from_number):
    """
    Get or create a Twilio conversation for a participant.
    Uses unique_name for efficient lookup and falls back to paginated search if needed.
    
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
        
        # Format from_number to ensure consistent comparison (E.164 format with whatsapp: prefix)
        from_phone = format_phone_number(from_number)
        formatted_from_number = f'whatsapp:{from_phone}'
        formatted_address = f'whatsapp:{participant_phone}'
        
        # Generate unique name for this conversation
        unique_name = _generate_conversation_unique_name(formatted_from_number, formatted_address)
        logger.info(f"unique_name: {unique_name}")
        
        # Strategy 1: Try to fetch conversation by unique_name (most efficient)
        # Use fetch() method to get conversation directly by unique_name
        # This prevents 409 errors when trying to create a duplicate
        try:
            conv = client.conversations.conversations(unique_name).fetch()
            # If we found a conversation with this unique_name, return it
            # The unique_name itself is the identifier, so we trust it
            logger.info(f"Found existing conversation by unique_name: {conv.sid} (unique_name={unique_name})")
            
            # Check if the correct participant exists, if not, we'll add it
            participant_exists = False
            try:
                participants = client.conversations.conversations(conv.sid).participants.list()
                for participant in participants:
                    if participant.messaging_binding:
                        participant_address = participant.messaging_binding.get('address')
                        participant_proxy_address = participant.messaging_binding.get('proxy_address')
                        
                        if (participant_address == formatted_address and 
                            participant_proxy_address == formatted_from_number):
                            participant_exists = True
                            break
            except Exception as participant_check_error:
                logger.warning(f"Error checking participants: {participant_check_error}")
            
            # If participant doesn't exist, add it
            if not participant_exists:
                try:
                    # Try dictionary syntax first (for older SDK versions), fallback to separate parameters (newer SDK)
                    try:
                        client.conversations.conversations(conv.sid).participants.create(
                            messaging_binding={
                                'address': formatted_address,
                                'proxy_address': formatted_from_number
                            }
                        )
                    except TypeError:
                        client.conversations.conversations(conv.sid).participants.create(
                            messaging_binding_address=formatted_address,
                            messaging_binding_proxy_address=formatted_from_number
                        )
                    logger.info(f"Added participant to existing conversation {conv.sid}")
                except Exception as add_participant_error:
                    # Participant might already exist or there's a conflict - that's okay
                    logger.error(f"Could not add participant (may already exist): {add_participant_error}")
            
            return conv.sid
        except Exception as e:
            # Conversation doesn't exist with this unique_name - that's okay, we'll create it
            logger.error(f"Conversation with unique_name={unique_name} does not exist yet: {e}")
        
        # Strategy 2: Try to create new conversation
        # If we get a 409 error (conversation already exists), fetch it by unique_name
        logger.info(f"Creating new conversation with unique_name={unique_name}")
        try:
            conversation = client.conversations.conversations.create(
                friendly_name=f"WhatsApp conversation with {participant_phone}",
                unique_name=unique_name
            )
            
            # Add participant to conversation
            try:
                # Try dictionary syntax first (for older SDK versions), fallback to separate parameters (newer SDK)
                try:
                    client.conversations.conversations(conversation.sid).participants.create(
                        messaging_binding={
                            'address': formatted_address,
                            'proxy_address': formatted_from_number
                        }
                    )
                except TypeError:
                    client.conversations.conversations(conversation.sid).participants.create(
                        messaging_binding_address=formatted_address,
                        messaging_binding_proxy_address=formatted_from_number
                    )
            except Exception as add_participant_error:
                logger.warning(f"Could not add participant to new conversation: {add_participant_error}")
            
            logger.info(f"Created new conversation: {conversation.sid} with unique_name={unique_name}")
            return conversation.sid
            
        except Exception as create_error:
            # Check if this is a 409 error (conversation already exists)
            error_str = str(create_error)
            if '409' in error_str or 'already exists' in error_str.lower() or 'unique name' in error_str.lower():
                logger.info(f"Conversation with unique_name={unique_name} already exists, fetching it")
                # Try to fetch it using fetch() method - it might have been created between our check and create attempt
                try:
                    conv = client.conversations.conversations(unique_name).fetch()
                    logger.info(f"Retrieved existing conversation: {conv.sid} (unique_name={unique_name})")
                    return conv.sid
                except Exception as fetch_error:
                    logger.error(f"Failed to fetch existing conversation after 409 error: {fetch_error}")
                    raise create_error  # Re-raise original error if we can't fetch it
            else:
                # Some other error occurred
                raise create_error
        
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
