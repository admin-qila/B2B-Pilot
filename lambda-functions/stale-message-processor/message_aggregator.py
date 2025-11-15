"""
Message Aggregator for WhatsApp Multi-Media Messages using Supabase

WhatsApp sends separate webhooks for each media item when users upload multiple images.
This aggregator collects related messages and processes them together after a short delay.
"""
import json
import time
import logging
import os
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from supabase import create_client, Client

logger = logging.getLogger(__name__)

def get_table_name(base_name: str) -> str:
    """Get the appropriate table name based on environment"""
    environment = os.environ.get("ENVIRONMENT", "prod")
    if environment == "staging":
        return f"{base_name}_staging"
    return base_name

class MessageAggregator:
    """Aggregates multiple WhatsApp media messages into a single unified message"""
    
    def __init__(self, supabase_url: str = None, supabase_key: str = None):
        """
        Initialize the message aggregator
        
        Args:
            supabase_url: Supabase project URL
            supabase_key: Supabase API key
        """
        self.supabase_url = supabase_url or os.environ.get('SUPABASE_URL')
        self.supabase_key = supabase_key or os.environ.get('SUPABASE_KEY')
        
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY are required")
        
        try:
            self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            raise
    
    def should_aggregate(self, unified_message) -> bool:
        """
        Determine if a message should be aggregated
        
        Args:
            unified_message: UnifiedMessage object
            
        Returns:
            bool: True if message should be aggregated (WhatsApp with media)
        """
        is_whatsapp = unified_message.client_type == "whatsapp"
        has_media = len(unified_message.media_items) > 0
        
        return is_whatsapp and has_media
    
    def aggregate_message(self, unified_message) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Aggregate a WhatsApp message with potential siblings
        
        Returns:
            tuple: (should_process_now, aggregated_message, group_key)
                - should_process_now: True if we should process immediately
                - aggregated_message: Combined message dict (if ready to process)
                - group_key: The aggregation group key
        """
        try:
            # Create group key: phone_number + timestamp window (10 seconds)
            # Messages within 10 seconds from same number are grouped
            current_time = int(time.time())
            time_window = 10  # seconds
            group_timestamp = current_time - (current_time % time_window)
            group_key = f"{unified_message.phone_number}#{group_timestamp}"
            
            # Check if group already exists
            response = self.supabase.table(get_table_name('whatsapp_message_groups'))\
                .select('*')\
                .eq('group_key', group_key)\
                .execute()
            
            if response.data and len(response.data) > 0:
                # Group exists, add our message to it
                item = response.data[0]
                messages = json.loads(item['messages'])
                
                # Add current message
                messages.append(unified_message.to_dict())
                
                # Update Supabase
                self.supabase.table(get_table_name('whatsapp_message_groups'))\
                    .update({
                        'messages': json.dumps(messages),
                        'message_count': len(messages),
                        'last_updated_at': datetime.utcnow().isoformat()
                    })\
                    .eq('group_key', group_key)\
                    .execute()
                
                logger.info(f"Added message to existing group {group_key}. Total: {len(messages)}")
                
                # Check if we should process now
                # Process if: 
                # 1. We have 3 messages (max), OR
                # 2. More than 3 seconds have passed since first message
                first_message_time = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
                time_elapsed = (datetime.utcnow() - first_message_time.replace(tzinfo=None)).total_seconds()
                
                should_process = len(messages) >= 3 or time_elapsed > 3
                
                if should_process:
                    # Delete the group and return aggregated message
                    self.supabase.table(get_table_name('whatsapp_message_groups'))\
                        .delete()\
                        .eq('group_key', group_key)\
                        .execute()
                    
                    aggregated = self._merge_messages(messages)
                    logger.info(f"Processing aggregated message with {len(messages)} items")
                    return True, aggregated, group_key
                else:
                    # Wait for more messages
                    logger.info(f"Waiting for more messages in group {group_key}")
                    return False, None, group_key
            
            else:
                # First message in group, create new entry
                messages = [unified_message.to_dict()]
                
                self.supabase.table(get_table_name('whatsapp_message_groups')).insert({
                    'group_key': group_key,
                    'phone_number': unified_message.phone_number,
                    'messages': json.dumps(messages),
                    'message_count': 1,
                    'created_at': datetime.utcnow().isoformat(),
                    'last_updated_at': datetime.utcnow().isoformat()
                }).execute()
                
                logger.info(f"Created new message group {group_key}")
                
                # Don't process immediately - wait for potential siblings
                return False, None, group_key
        
        except Exception as e:
            logger.error(f"Error in message aggregation: {e}")
            # On error, process message immediately to avoid data loss
            return True, unified_message.to_dict(), None
    
    def _merge_messages(self, messages: List[Dict]) -> Dict:
        """
        Merge multiple messages into a single unified message
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            Dict: Merged message with all media items
        """
        if not messages:
            return {}
        
        # Use first message as base
        merged = messages[0].copy()
        
        # Collect all media items from all messages
        all_media_items = []
        for msg in messages:
            all_media_items.extend(msg.get('media_items', []))
        
        # Limit to 3 media items
        merged['media_items'] = all_media_items[:3]
        
        # Combine text bodies (if any)
        text_bodies = [msg.get('text_body', '') for msg in messages if msg.get('text_body')]
        if text_bodies:
            merged['text_body'] = ' | '.join(text_bodies)
        
        logger.info(f"Merged {len(messages)} messages into one with {len(merged['media_items'])} media items")
        
        return merged
    
    def process_stale_messages(self, max_age_seconds: int = 10) -> List[Dict]:
        """
        Process any messages that have been waiting too long
        This should be called by a scheduled job (e.g., CloudWatch Events or Supabase cron)
        
        Args:
            max_age_seconds: Maximum age before processing stale messages
            
        Returns:
            List of aggregated messages ready to process
        """
        try:
            # Calculate cutoff time
            cutoff_time = datetime.utcnow() - timedelta(seconds=max_age_seconds)
            
            # Find stale message groups
            response = self.supabase.table(get_table_name('whatsapp_message_groups'))\
                .select('*')\
                .lt('created_at', cutoff_time.isoformat())\
                .execute()
            
            stale_messages = []
            
            for item in response.data:
                group_key = item['group_key']
                messages = json.loads(item['messages'])
                
                # Merge and prepare for processing
                aggregated = self._merge_messages(messages)
                stale_messages.append(aggregated)
                
                # Delete the group
                self.supabase.table(get_table_name('whatsapp_message_groups'))\
                    .delete()\
                    .eq('group_key', group_key)\
                    .execute()
                
                logger.info(f"Processed stale message group {group_key} with {len(messages)} messages")
            
            return stale_messages
        
        except Exception as e:
            logger.error(f"Error processing stale messages: {e}")
            return []
    
    def cleanup_expired_groups(self, max_age_minutes: int = 5):
        """
        Cleanup expired message groups (older than max_age_minutes)
        This prevents orphaned groups from accumulating
        
        Args:
            max_age_minutes: Maximum age in minutes before cleanup
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(minutes=max_age_minutes)
            
            response = self.supabase.table(get_table_name('whatsapp_message_groups'))\
                .delete()\
                .lt('created_at', cutoff_time.isoformat())\
                .execute()
            
            logger.info(f"Cleaned up expired message groups")
            
        except Exception as e:
            logger.error(f"Error cleaning up expired groups: {e}")


# Utility function to get aggregator instance
_aggregator_instance = None

def get_aggregator() -> MessageAggregator:
    """Get or create a singleton MessageAggregator instance"""
    global _aggregator_instance
    if _aggregator_instance is None:
        _aggregator_instance = MessageAggregator()
    return _aggregator_instance
