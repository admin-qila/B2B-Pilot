"""
Shared configuration for Lambda functions
"""
import os
import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS Configuration
SQS_DLQ_URL = os.environ.get('SQS_DLQ_URL')

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')  # Your Twilio WhatsApp number
RESPONSE_FEEDBACK_TEMPLATE = os.environ.get('RESPONSE_FEEDBACK_TEMPLATE')

# Supabase Configuration (if needed)
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

# Processing Configuration
MAX_PROCESSING_TIME_SECONDS = 300  # 5 minutes max for background processing
VISIBILITY_TIMEOUT = 360  # 6 minutes visibility timeout for SQS

# Validate critical environment variables
def validate_config():
    """Validate that all required environment variables are set"""
    required_vars = {
        'TWILIO_ACCOUNT_SID': TWILIO_ACCOUNT_SID,
        'TWILIO_AUTH_TOKEN': TWILIO_AUTH_TOKEN,
        'TWILIO_PHONE_NUMBER': TWILIO_PHONE_NUMBER
    }
    
    missing_vars = [var for var, value in required_vars.items() if not value]
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
