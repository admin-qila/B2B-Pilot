"""
Unified message parsing for different client types
"""
import json
import uuid
import urllib.parse
import base64
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from client_utils import ClientType, get_client_config

logger = logging.getLogger(__name__)

@dataclass
class MediaItem:
    """Represents a media item (image, video, etc.)"""
    url: Optional[str] = None  # For Twilio media URLs
    s3_key: Optional[str] = None  # For pre-uploaded S3 media
    content_type: Optional[str] = None
    size: Optional[int] = None

@dataclass
class UnifiedMessage:
    """Unified message structure that can be populated from any client type"""
    message_id: str
    client_type: str
    timestamp: str
    phone_number: str  # E.164 format without whatsapp: prefix
    from_number: str  # Original format from client
    to_number: str  # Original format from client
    text_body: str
    media_items: List[MediaItem]
    button_payload: str = ""
    button_text: str = ""
    twilio_message_sid: Optional[str] = None
    account_sid: Optional[str] = None
    message_status: Optional[str] = None
    original_params: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None  # For webapp/mobile clients
    session_id: Optional[str] = None  # For webapp/mobile clients
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        # Convert MediaItem objects to dicts
        result['media_items'] = [asdict(item) for item in self.media_items]
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UnifiedMessage':
        """Create UnifiedMessage from dictionary"""
        # Convert media_items back to MediaItem objects
        media_items = [MediaItem(**item) for item in data.get('media_items', [])]
        data['media_items'] = media_items
        return cls(**data)

class MessageParser:
    """Parses messages from different client types into unified format"""
    
    @staticmethod
    def parse_message(event: Dict[str, Any], client_type: ClientType) -> UnifiedMessage:
        """
        Parse message from API Gateway event based on client type
        
        Args:
            event: API Gateway event
            client_type: Detected client type
            
        Returns:
            UnifiedMessage instance
        """
        if client_type == ClientType.WHATSAPP:
            return MessageParser._parse_whatsapp_message(event)
        elif client_type in [ClientType.WEBAPP, ClientType.MOBILE]:
            return MessageParser._parse_json_message(event, client_type)
        else:
            raise ValueError(f"Unsupported client type: {client_type}")
    
    @staticmethod
    def _parse_whatsapp_message(event: Dict[str, Any]) -> UnifiedMessage:
        """Parse Twilio WhatsApp webhook message"""
        body = event.get('body', '')
        is_base64 = event.get('isBase64Encoded', False)
        
        if is_base64:
            body = base64.b64decode(body).decode('utf-8')
        
        # Parse form data
        params = urllib.parse.parse_qs(body)
        # Convert to single-value dict (Twilio sends single values)
        params = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in params.items()}
        
        # Extract media URLs
        media_items = []
        num_media = int(params.get('NumMedia', 0))
        for i in range(num_media):
            media_url = params.get(f'MediaUrl{i}')
            media_type = params.get(f'MediaContentType{i}')
            if media_url:
                media_items.append(MediaItem(
                    url=media_url,
                    content_type=media_type
                ))
        
        # Format phone number (remove whatsapp: prefix)
        from_number = params.get('From', '')
        phone_number = from_number.replace('whatsapp:', '') if from_number.startswith('whatsapp:') else from_number
        
        return UnifiedMessage(
            message_id=str(uuid.uuid4()),
            client_type=ClientType.WHATSAPP.value,
            timestamp=datetime.utcnow().isoformat(),
            phone_number=phone_number,
            from_number=from_number,
            to_number=params.get('To', ''),
            text_body=params.get('Body', ''),
            media_items=media_items,
            button_payload=params.get('ButtonPayload', ''),
            button_text=params.get('ButtonText', ''),
            twilio_message_sid=params.get('MessageSid', ''),
            account_sid=params.get('AccountSid', ''),
            message_status=params.get('SmsStatus', ''),
            original_params=params
        )
    
    @staticmethod
    def _parse_json_message(event: Dict[str, Any], client_type: ClientType) -> UnifiedMessage:
        """Parse JSON message from webapp/mobile clients"""
        body = event.get('body', '{}')
        is_base64 = event.get('isBase64Encoded', False)
        
        if is_base64:
            body = base64.b64decode(body).decode('utf-8')
        
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON body: {body}")
            data = {}
        
        # Extract media items from s3_keys
        media_items = []
        s3_keys = data.get('s3_keys', [])
        if isinstance(s3_keys, str):
            s3_keys = [s3_keys]
        
        for s3_key in s3_keys:
            if isinstance(s3_key, dict):
                media_items.append(MediaItem(
                    s3_key=s3_key.get('key'),
                    content_type=s3_key.get('content_type'),
                    size=s3_key.get('size')
                ))
            else:
                media_items.append(MediaItem(s3_key=s3_key))
        
        # Handle single s3_key field as well
        single_s3_key = data.get('s3_key')
        if single_s3_key and not media_items:
            media_items.append(MediaItem(s3_key=single_s3_key))
        
        phone_number = data.get('phone_number', '')
        
        # Extract text body - check multiple possible field names
        text_body = data.get('text', data.get('message', data.get('additionalText', '')))
        
        return UnifiedMessage(
            message_id=data.get('message_id', str(uuid.uuid4())),
            client_type=client_type.value,
            timestamp=data.get('timestamp', datetime.utcnow().isoformat()),
            phone_number=phone_number,
            from_number=phone_number,  # For non-WhatsApp, from = phone_number
            to_number=data.get('to_number', ''),
            text_body=text_body,
            media_items=media_items,
            button_payload=data.get('button_payload', ''),
            button_text=data.get('button_text', ''),
            user_id=data.get('user_id'),
            session_id=data.get('session_id'),
            original_params=data
        )

    @staticmethod
    def create_sqs_message(unified_message: UnifiedMessage) -> Dict[str, Any]:
        """
        Create SQS message from unified message
        
        Args:
            unified_message: UnifiedMessage instance
            
        Returns:
            Dictionary for SQS message body and attributes
        """
        message_body = unified_message.to_dict()
        
        # Create message attributes for SQS filtering/routing
        message_attributes = {
            'messageType': {
                'StringValue': f'{unified_message.client_type}-message',
                'DataType': 'String'
            },
            'clientType': {
                'StringValue': unified_message.client_type,
                'DataType': 'String'
            },
            'phoneNumber': {
                'StringValue': unified_message.phone_number,
                'DataType': 'String'
            },
            'hasMedia': {
                'StringValue': str(len(unified_message.media_items) > 0),
                'DataType': 'String'
            }
        }
        
        # Add user_id if present (for webapp/mobile)
        if unified_message.user_id:
            message_attributes['userId'] = {
                'StringValue': unified_message.user_id,
                'DataType': 'String'
            }
        
        return {
            'message_body': json.dumps(message_body),
            'message_attributes': message_attributes
        }