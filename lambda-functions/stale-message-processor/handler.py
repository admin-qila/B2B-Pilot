"""
Lambda function to process stale WhatsApp message groups
This runs on a schedule (e.g., every 10 seconds) to process messages that didn't
reach the 3-message threshold or time limit in the webhook handler
"""
import json
import boto3
import logging
import os
import sys

# Add shared module to path
sys.path.append('/opt/python')
sys.path.append('/opt/shared')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'webhook-handler'))

from message_aggregator import get_aggregator
from message_parser import UnifiedMessage, MessageParser

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize SQS client
sqs = boto3.client('sqs')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')


def lambda_handler(event, context):
    """
    Process stale message groups and send them to SQS
    
    This function is triggered by CloudWatch Events on a schedule
    (e.g., every 10 seconds) to ensure messages are eventually processed
    even if they don't reach the aggregation threshold
    """
    try:
        logger.info("Starting stale message processor")
        
        # Get aggregator instance
        aggregator = get_aggregator()
        
        # Process messages older than 5 seconds
        stale_messages = aggregator.process_stale_messages(max_age_seconds=5)
        
        if not stale_messages:
            logger.info("No stale messages to process")
            return {
                'statusCode': 200,
                'body': json.dumps({'processed': 0, 'message': 'No stale messages'})
            }
        
        # Send each stale message to SQS
        processed_count = 0
        failed_count = 0
        
        for message_dict in stale_messages:
            try:
                # Convert dict to UnifiedMessage
                unified_message = UnifiedMessage.from_dict(message_dict)
                
                # Create SQS message
                sqs_message_data = MessageParser.create_sqs_message(unified_message)
                
                # Send to SQS
                response = sqs.send_message(
                    QueueUrl=SQS_QUEUE_URL,
                    MessageBody=sqs_message_data['message_body'],
                    MessageAttributes=sqs_message_data['message_attributes']
                )
                
                logger.info(f"Sent stale message to SQS. MessageId: {response['MessageId']}, "
                          f"Phone: {unified_message.phone_number}, Media items: {len(unified_message.media_items)}")
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Failed to process stale message: {e}")
                failed_count += 1
        
        logger.info(f"Stale message processing complete. Processed: {processed_count}, Failed: {failed_count}")
        
        # Cleanup expired groups (older than 5 minutes)
        try:
            aggregator.cleanup_expired_groups(max_age_minutes=5)
        except Exception as e:
            logger.error(f"Failed to cleanup expired groups: {e}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'processed': processed_count,
                'failed': failed_count,
                'message': f'Processed {processed_count} stale messages'
            })
        }
        
    except Exception as e:
        logger.error(f"Error in stale message processor: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
