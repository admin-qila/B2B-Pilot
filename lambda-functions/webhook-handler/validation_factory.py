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
            
            # Debug logging
            logger.info(f"=== Twilio Webhook Validation Debug ===")
            logger.info(f"Request method: {request_context.get('httpMethod', 'unknown')}")
            logger.info(f"Content-Type header: {headers.get('Content-Type', headers.get('content-type', 'not found'))}")
            logger.info(f"Body length: {len(body)}")
            logger.info(f"Body (first 200 chars): {body[:200]}")
            logger.info(f"Domain: {domain}")
            logger.info(f"Stage: {stage}")
            logger.info(f"Resource path: {resource_path}")
            logger.info(f"Constructed URL: {full_url}")
            logger.info(f"Auth token present: {bool(auth_token)}")
            logger.info(f"Auth token starts with: {auth_token[:8] if auth_token else 'None'}...")
            logger.info(f"Signature: {signature[:15] if signature else 'None'}...")
            logger.info(f"Parsed params count: {len(params)}")
            logger.info(f"Params keys: {sorted(list(params.keys()))}")
            logger.info(f"=== End Debug Info ===")
            
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
    
    @staticmethod
    def check_allowlist(phone_number: str, client_type: ClientType) -> Tuple[bool, Optional[str]]:
        """
        Check if phone number is in allowlist (only for WhatsApp for now)
        
        Args:
            phone_number: Phone number to check
            client_type: Client type
            
        Returns:
            Tuple of (is_allowed, error_message)
        """
        if client_type != ClientType.WHATSAPP:
            # For non-WhatsApp clients, allowlist check might be handled differently
            # or not at all (e.g., through user authentication)
            return True, None
        
        # WhatsApp allowlist (same as before)
        ALLOWLIST = {
            "Vikram C": "+16504557855",
            "Suneet K": "+919975079915",
            "Rohan K": "+15713145732",
            "Ntasha": "+918595751144",
            "Urmila": "+919881248127",
            "Saleel": "+919850985957",
            "Puny": "+94773504544",
            "Varun": "+13095309527",
            "Sanchit": "+919818613953",
            "Vinod": "+919811304081",
            "Sunita": "+919811610960",
            "Ashish": "+919665889999",
            "Mayank": "+919890123733",
            "Ingrid": "+14157869353",
            "Rona": "+919870797369",
            "Vikram Vishram": "+919425013781",
            "Flavio": "+919819847482",
            "Natasha": "+16024417199",
            "Priyanka": "+61413942458",
            "Rolph": "+447931952977",
            "Alroy": "+61422641572",
            "Will": "+15137225025",
            "Rebel": "+17036783894",
            "Amila": "+13144000552",
            "Ani": "+12672433804",
            "Neha": "+15714200153",
            "Vinit": "+15129130948",
            "Rucha": "+919619717851",
            "Nikhil": "+12026038673",
            "Vikram Dave": "+14084060367",
            "Mihir": "+917798215084",
            "Adarsh": "+14254433863",
            "Snigdha": "+4553844318",
            "Kunal Pachamatia": "+4540444030",
            "Kunal Pradhan": "+919619059395",
            "Parneet": "+919560180001",
            "Unni": "+919820834678",
            "Taneia": "+919820420638",
            "Anup": "+919822777362",
            "Jody Miller": "+13146141590",
            "Nath": "+17036296679",
            "Radha": "+917042915167",
            "Utkarsh": "+19252097391",
            "Santosh": "+14083558246",
            "Parag": "+12026038674",
            "Prajakta": "+14154505802",
            "Amit Shetye": "+17867971627",
            "Nanda Ogale": "+919920122813",
            "Anuj Sampathkumaran": "+18583355286",
            "Debolina B": "+14084776739",
            "Swaraj C": "+17035048456",
            "Rafeek": "+919847920104",
            "Shalima": "+919447169042",
            "CIMS mobile": "+919061030104"
        }
        
        # Format phone number for comparison
        formatted_number = phone_number.replace('whatsapp:', '') if phone_number.startswith('whatsapp:') else phone_number
        
        # Check allowlist
        allowlist_numbers = set(ALLOWLIST.values())
        if formatted_number not in allowlist_numbers:
            return False, "Phone number not in allowlist"
        
        return True, None
