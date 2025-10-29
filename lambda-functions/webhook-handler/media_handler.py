"""
Media handling for different client types
"""
import os
import requests
import base64
import logging
from typing import Tuple, Optional
from client_utils import ClientType
from message_parser import MediaItem

logger = logging.getLogger(__name__)

class MediaHandler:
    """Handles media processing for different client types"""
    
    @staticmethod
    def download_media(media_item: MediaItem, client_type: ClientType) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """
        Download media based on client type
        
        Args:
            media_item: MediaItem with URL or S3 key
            client_type: Client type
            
        Returns:
            Tuple of (success, media_bytes, content_type)
        """
        if client_type == ClientType.WHATSAPP and media_item.url:
            return MediaHandler._download_twilio_media(media_item)
        elif client_type in [ClientType.WEBAPP, ClientType.MOBILE] and media_item.s3_key:
            return MediaHandler._download_s3_media(media_item)
        else:
            logger.error(f"No media source available for {client_type.value}")
            return False, None, None
    
    @staticmethod
    def _download_twilio_media(media_item: MediaItem) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """Download media from Twilio URL"""
        try:
            media_url = media_item.url
            
            # Regular Twilio media URL - download with authentication
            auth = (
                os.getenv("TWILIO_ACCOUNT_SID", os.environ.get('TWILIO_ACCOUNT_SID')), 
                os.getenv("TWILIO_AUTH_TOKEN", os.environ.get('TWILIO_AUTH_TOKEN'))
            )
            
            response = requests.get(media_url, auth=auth, timeout=30)
            response.raise_for_status()
            
            content_type = response.headers.get('content-type', media_item.content_type or 'application/octet-stream')
            
            return True, response.content, content_type
            
        except requests.exceptions.Timeout:
            logger.error("Timeout downloading Twilio media")
            return False, None, None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading Twilio media: {e}")
            return False, None, None
        except Exception as e:
            logger.error(f"Unexpected error downloading Twilio media: {e}")
            return False, None, None
    
    @staticmethod
    def _download_s3_media(media_item: MediaItem) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """Download media from S3"""
        try:
            import boto3
            
            s3_client = boto3.client('s3')
            bucket_name = os.environ.get('S3_BUCKET_NAME')
            
            if not bucket_name:
                logger.error("S3_BUCKET_NAME environment variable not set")
                return False, None, None
            
            # Download from S3
            response = s3_client.get_object(Bucket=bucket_name, Key=media_item.s3_key)
            media_bytes = response['Body'].read()
            
            # Get content type from S3 metadata or MediaItem
            content_type = response.get('ContentType') or media_item.content_type or 'application/octet-stream'
            
            return True, media_bytes, content_type
            
        except Exception as e:
            logger.error(f"Error downloading S3 media: {e}")
            return False, None, None
    
    @staticmethod
    def upload_to_s3(
        media_bytes: bytes, 
        phone_number: str, 
        submission_id: str, 
        content_type: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Upload media to S3
        
        Args:
            media_bytes: Media content as bytes
            phone_number: User's phone number
            submission_id: Unique submission ID
            content_type: MIME content type
            
        Returns:
            Tuple of (success, s3_key)
        """
        try:
            from s3_service import get_s3_service
            
            s3_service = get_s3_service()
            if not s3_service:
                logger.error("S3 service not available")
                return False, None
            
            upload_success, s3_key = s3_service.upload_image(
                image_data=media_bytes,
                phone_number=phone_number,
                submission_id=submission_id,
                content_type=content_type
            )
            
            return upload_success, s3_key
            
        except Exception as e:
            logger.error(f"Error uploading to S3: {e}")
            return False, None