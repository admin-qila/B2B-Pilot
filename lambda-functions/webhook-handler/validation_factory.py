"""
Validation factory for different client types
"""
import os
import urllib.parse
import logging
from typing import Dict, Any, Tuple, Optional
from twilio.request_validator import RequestValidator
from client_utils import ClientType

logger = logging.getLogger(__name__)

class ValidationFactory:
    """Factory for validating requests from different client types"""
    
    @staticmethod
    def validate_request(event: Dict[str, Any], client_type: ClientType) -> Tuple[bool, Optional[str]]:
        """
        Validate request based on client type
        
        Args:
            event: API Gateway event
            client_type: Detected client type
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if client_type == ClientType.WHATSAPP:
            return ValidationFactory._validate_twilio_webhook(event)
        elif client_type in [ClientType.WEBAPP, ClientType.MOBILE]:
            return ValidationFactory._validate_api_request(event, client_type)
        else:
            return False, f"Unsupported client type: {client_type.value}"
    
    @staticmethod
    def _validate_twilio_webhook(event: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate Twilio webhook signature"""
        try:
            # Get Twilio auth token
            auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
            if not auth_token:
                return False, "Missing TWILIO_AUTH_TOKEN environment variable"
            
            headers = event.get('headers', {})
            
            # Get Twilio signature from headers (case insensitive)
            signature = None
            for key, value in headers.items():
                if key.lower() == 'x-twilio-signature':
                    signature = value
                    break
            
            if not signature:
                return False, "Missing Twilio signature header"
            
            # Parse the form-encoded body
            body = event.get('body', '')
            is_base64 = event.get('isBase64Encoded', False)
            
            if is_base64:
                import base64
                body = base64.b64decode(body).decode('utf-8')
            
            # Parse form data - Twilio sends application/x-www-form-urlencoded
            # For Twilio validation, we need the parameters as they were sent
            try:
                params = urllib.parse.parse_qs(body, keep_blank_values=True)
                # Convert to single-value dict but preserve the original format for validation
                # Twilio expects the original form-encoded string for signature validation
                form_params = {}
                for k, v in params.items():
                    if isinstance(v, list) and len(v) == 1:
                        form_params[k] = v[0]
                    elif isinstance(v, list) and len(v) == 0:
                        form_params[k] = ''
                    else:
                        form_params[k] = v
                params = form_params
            except Exception as e:
                logger.error(f"Error parsing form parameters: {e}")
                return False, f"Error parsing form parameters: {str(e)}"
            
            # Construct the full URL
            domain = headers.get('Host') or headers.get('host')
            protocol = 'https'  # API Gateway always uses HTTPS externally
            
            # Get the request context to build the correct URL
            request_context = event.get('requestContext', {})
            stage = request_context.get('stage', 'prod')
            resource_path = event.get('resource', '/sms')  # This is the resource path like /sms
            
            # Construct the path with stage
            # API Gateway URLs have format: https://domain/stage/resource
            path = f"/{stage}{resource_path}" if not resource_path.startswith('/') else f"/{stage}{resource_path}"
            
            # Include query parameters if any
            query_params = event.get('queryStringParameters', {})
            query_string = urllib.parse.urlencode(query_params) if query_params else ''
            
            # Construct the full URL that matches what Twilio is actually posting to
            full_url = f"{protocol}://{domain}{path}"
            if query_string:
                full_url += f"?{query_string}"
            
            # Validate the webhook
            validator = RequestValidator(auth_token)
            
            # Try the constructed URL first
            logger.info(f"Attempting validation with constructed URL: {full_url}")
            if validator.validate(full_url, params, signature):
                logger.info("Webhook validated successfully with constructed URL")
                return True, None
            
            # Fallback 1: Try with the original path from event (without stage construction)
            original_path = event.get('path', '/sms')
            fallback_url_1 = f"{protocol}://{domain}{original_path}"
            if query_string:
                fallback_url_1 += f"?{query_string}"
            
            logger.info(f"Attempting validation with fallback URL 1: {fallback_url_1}")
            if validator.validate(fallback_url_1, params, signature):
                logger.info("Webhook validated successfully with fallback URL 1")
                return True, None
            
            # Fallback 2: Try HTTP versions (for local development)
            http_url = full_url.replace('https://', 'http://', 1)
            logger.info(f"Attempting validation with HTTP URL: {http_url}")
            if validator.validate(http_url, params, signature):
                logger.info("Webhook validated with HTTP URL conversion")
                return True, None
            
            # Fallback 3: Try without query parameters
            if query_string:
                base_url = f"{protocol}://{domain}{path}"
                logger.info(f"Attempting validation without query params: {base_url}")
                if validator.validate(base_url, params, signature):
                    logger.info("Webhook validated without query parameters")
                    return True, None
            
            logger.warning(f"Failed to validate Twilio webhook signature for all attempted URLs")
            logger.warning(f"Primary URL: {full_url}")
            logger.warning(f"Fallback URL: {fallback_url_1}")
            return False, "Invalid Twilio webhook signature"
            
        except Exception as e:
            logger.error(f"Error validating Twilio webhook: {e}")
            return False, f"Webhook validation error: {str(e)}"
    
    @staticmethod
    def _validate_api_request(event: Dict[str, Any], client_type: ClientType) -> Tuple[bool, Optional[str]]:
        """Validate API request from webapp/mobile clients"""
        try:
            headers = event.get('headers', {})
            
            # Check for authorization header
            auth_header = headers.get('Authorization') or headers.get('authorization')
            api_key = headers.get('X-API-Key') or headers.get('x-api-key')
            
            if not (auth_header or api_key):
                return False, "Missing authorization header or API key"
            
            # For now, we'll do basic validation
            # In production, you'd validate JWT tokens or API keys against your auth system
            
            if api_key:
                # Validate API key
                expected_api_key = os.environ.get('API_KEY')
                if expected_api_key and api_key != expected_api_key:
                    return False, "Invalid API key"
            
            if auth_header:
                # Basic JWT validation (you'd implement proper JWT validation here)
                if not auth_header.startswith('Bearer '):
                    return False, "Invalid authorization header format"
                
                # Extract token
                token = auth_header.replace('Bearer ', '')
                if not token:
                    return False, "Missing bearer token"
                
                # TODO: Add proper JWT validation here
                # For now, just check if token is not empty
                pass
            
            return True, None
            
        except Exception as e:
            logger.error(f"Error validating API request: {e}")
            return False, f"API validation error: {str(e)}"