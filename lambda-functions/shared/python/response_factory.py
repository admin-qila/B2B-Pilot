"""
Response factory for different client types
"""
import json
import logging
from typing import Dict, Any, Optional
from twilio.twiml.messaging_response import MessagingResponse
from client_utils import ClientType, get_client_config

logger = logging.getLogger(__name__)

class ResponseFactory:
    """Factory for creating responses for different client types"""
    
    @staticmethod
    def create_success_response(
        client_type: ClientType, 
        message: str = None,
        button_text: str = None,
        data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Create success response based on client type
        
        Args:
            client_type: Client type
            message: Success message
            button_text: Button text (for WhatsApp feedback responses)
            data: Additional data to include in response
            
        Returns:
            API Gateway response dictionary
        """
        config = get_client_config(client_type)
        
        if config['response_format'] == 'twiml':
            return ResponseFactory._create_twiml_success_response(message, button_text)
        else:
            return ResponseFactory._create_json_success_response(message, data)
    
    @staticmethod
    def create_error_response(
        client_type: ClientType, 
        error_message: str = None,
        status_code: int = 500,
        error_code: str = None
    ) -> Dict[str, Any]:
        """
        Create error response based on client type
        
        Args:
            client_type: Client type
            error_message: Error message
            status_code: HTTP status code
            error_code: Application-specific error code
            
        Returns:
            API Gateway response dictionary
        """
        config = get_client_config(client_type)
        
        if config['response_format'] == 'twiml':
            return ResponseFactory._create_twiml_error_response(error_message, status_code)
        else:
            return ResponseFactory._create_json_error_response(error_message, status_code, error_code)
    
    @staticmethod
    def create_validation_error_response(
        client_type: ClientType,
        validation_message: str
    ) -> Dict[str, Any]:
        """
        Create validation error response
        
        Args:
            client_type: Client type
            validation_message: Validation error message
            
        Returns:
            API Gateway response dictionary
        """
        if client_type == ClientType.WHATSAPP:
            # For WhatsApp, return success but don't process
            return ResponseFactory._create_twiml_success_response(validation_message)
        else:
            return ResponseFactory._create_json_error_response(
                validation_message, 
                401, 
                "VALIDATION_ERROR"
            )
    
    @staticmethod
    def create_allowlist_error_response(client_type: ClientType) -> Dict[str, Any]:
        """
        Create allowlist error response
        
        Args:
            client_type: Client type
            
        Returns:
            API Gateway response dictionary
        """
        message = "🚫 Sorry, this service is currently in beta and available only to selected users. Please contact admin@qilafy.com for access."
        
        if client_type == ClientType.WHATSAPP:
            return ResponseFactory._create_twiml_success_response(message)
        else:
            return ResponseFactory._create_json_error_response(
                "Access denied. Service available only to selected users.",
                403,
                "ALLOWLIST_ERROR"
            )
    
    @staticmethod
    def _create_twiml_success_response(message: str = None, button_text: str = None) -> Dict[str, Any]:
        """Create TwiML success response for WhatsApp"""
        resp = MessagingResponse()
        
        if button_text and button_text.strip():
            resp.message("Thank you for your feedback 🙏")
        elif message:
            resp.message(message)
        else:
            resp.message("Your data is being analyzed 🔍 We'll get back to you shortly ⏳")
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/xml"
            },
            "body": str(resp)
        }
    
    @staticmethod
    def _create_twiml_error_response(message: str = None, status_code: int = 500) -> Dict[str, Any]:
        """Create TwiML error response for WhatsApp"""
        resp = MessagingResponse()
        
        if message:
            resp.message(message)
        else:
            resp.message("There was an error analyzing your request, kindly retry")
        
        return {
            "statusCode": status_code,
            "headers": {
                "Content-Type": "application/xml"
            },
            "body": str(resp)
        }
    
    @staticmethod
    def _create_json_success_response(message: str = None, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create JSON success response for webapp/mobile clients"""
        response_data = {
            "success": True,
            "status": "received"
        }
        
        if message:
            response_data["message"] = message
        
        if data:
            response_data.update(data)
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",  # Configure as needed
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Client-Type",
                "Access-Control-Allow-Methods": "POST,OPTIONS"
            },
            "body": json.dumps(response_data)
        }
    
    @staticmethod
    def _create_json_error_response(
        message: str = None, 
        status_code: int = 500, 
        error_code: str = None
    ) -> Dict[str, Any]:
        """Create JSON error response for webapp/mobile clients"""
        response_data = {
            "success": False,
            "error": message or "An error occurred"
        }
        
        if error_code:
            response_data["error_code"] = error_code
        
        return {
            "statusCode": status_code,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",  # Configure as needed
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Client-Type",
                "Access-Control-Allow-Methods": "POST,OPTIONS"
            },
            "body": json.dumps(response_data)
        }