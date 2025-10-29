"""
Client type detection and handling utilities
"""
import json
import logging
from enum import Enum
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class ClientType(Enum):
    WHATSAPP = "whatsapp"
    WEBAPP = "webapp"
    MOBILE = "mobile"
    UNKNOWN = "unknown"

def detect_client_type(event: Dict[str, Any]) -> ClientType:
    """
    Detect client type based on headers and request structure
    
    Args:
        event: API Gateway event
    
    Returns:
        ClientType enum value
    """
    headers = event.get('headers', {})
    
    # Check for Twilio signature header (case insensitive)
    twilio_signature = None
    for key, value in headers.items():
        if key.lower() == 'x-twilio-signature':
            twilio_signature = value
            break
    
    if twilio_signature:
        return ClientType.WHATSAPP
    
    # Check for custom client headers
    client_type_header = headers.get('X-Client-Type') or headers.get('x-client-type')
    if client_type_header:
        client_type_lower = client_type_header.lower()
        if client_type_lower == 'webapp':
            return ClientType.WEBAPP
        elif client_type_lower == 'mobile':
            return ClientType.MOBILE
    
    # Check content type to infer client type
    content_type = headers.get('Content-Type') or headers.get('content-type', '')
    
    # Twilio sends form-encoded data
    if 'application/x-www-form-urlencoded' in content_type:
        return ClientType.WHATSAPP
    
    # Other clients likely send JSON
    if 'application/json' in content_type:
        # Default to webapp if no specific header
        return ClientType.WEBAPP
    
    return ClientType.UNKNOWN

def get_client_config(client_type: ClientType) -> Dict[str, Any]:
    """
    Get configuration specific to client type
    
    Args:
        client_type: ClientType enum value
    
    Returns:
        Dictionary with client-specific configuration
    """
    configs = {
        ClientType.WHATSAPP: {
            'requires_twilio_validation': True,
            'expects_form_data': True,
            'response_format': 'twiml',
            'media_source': 'twilio_url',
            'supports_buttons': True,
            'phone_number_format': 'whatsapp_prefixed'
        },
        ClientType.WEBAPP: {
            'requires_twilio_validation': False,
            'expects_form_data': False,
            'response_format': 'json',
            'media_source': 's3_key',
            'supports_buttons': False,
            'phone_number_format': 'e164'
        },
        ClientType.MOBILE: {
            'requires_twilio_validation': False,
            'expects_form_data': False,
            'response_format': 'json',
            'media_source': 's3_key',
            'supports_buttons': False,
            'phone_number_format': 'e164'
        },
        ClientType.UNKNOWN: {
            'requires_twilio_validation': False,
            'expects_form_data': False,
            'response_format': 'json',
            'media_source': 's3_key',
            'supports_buttons': False,
            'phone_number_format': 'e164'
        }
    }
    
    return configs.get(client_type, configs[ClientType.UNKNOWN])

def validate_client_request(event: Dict[str, Any], client_type: ClientType) -> Tuple[bool, Optional[str]]:
    """
    Validate request based on client type
    
    Args:
        event: API Gateway event
        client_type: Detected client type
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    config = get_client_config(client_type)
    
    if client_type == ClientType.WHATSAPP:
        # Twilio validation will be handled separately
        return True, None
    
    elif client_type in [ClientType.WEBAPP, ClientType.MOBILE]:
        # Check for API key or authorization header
        headers = event.get('headers', {})
        auth_header = headers.get('Authorization') or headers.get('authorization')
        api_key = headers.get('X-API-Key') or headers.get('x-api-key')
        
        if not (auth_header or api_key):
            return False, "Missing authorization header or API key"
        
        # Additional validation can be added here (JWT verification, API key validation)
        return True, None
    
    return False, f"Unsupported client type: {client_type.value}"