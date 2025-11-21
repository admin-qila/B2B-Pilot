"""
Database models and utilities for Qila Scam Detection Service
Integrates with Supabase PostgreSQL database
"""

import os
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Tuple, Any, Union
from dataclasses import dataclass
from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
environment = os.environ.get("ENVIRONMENT", "prod")

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

supabase: Client = create_client(supabase_url, supabase_key)
logger.info("Supabase client initialized successfully")

def get_table_name(base_name: str) -> str:
    """Get the appropriate table name based on environment"""
    if environment == "staging":
        return f"{base_name}_staging"
    return base_name

@dataclass
class UserSubmission:
    """Data class for user submissions
    
    Note: image_url and s3_key can be either:
    - String: Single image (backward compatible)
    - List[str]: Multiple images (up to 3)
    """
    id: Optional[str] = None
    phone_number: str = ""
    image_url: Optional[Union[str, List[str]]] = None  # Single URL or list of URLs
    s3_key: Optional[Union[str, List[str]]] = None  # Single S3 key or list of S3 keys
    prediction_result: Optional[Dict] = None
    confidence_score: Optional[float] = None
    scam_label: Optional[str] = None
    processing_time_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    feedback_text: Optional[str] = None
    feedback_timestamp: Optional[datetime] = None
    input_text: Optional[str] = None
    message_id: Optional[str] = None  # SNS Message ID for idempotency

@dataclass
class UsageInfo:
    """Data class for usage tracking information"""
    can_proceed: bool
    current_count: int
    daily_limit: int
    time_until_reset: timedelta

@dataclass
class AnalyticsSummary:
    """Data class for analytics summary"""
    date: date
    total_submissions: int = 0
    scam_detected: int = 0
    not_scam_detected: int = 0
    likely_scam_detected: int = 0
    unique_users: int = 0
    users_hit_limit: int = 0
    avg_confidence_score: Optional[float] = None
    avg_processing_time_ms: Optional[int] = None
    feedback_count: int = 0

class DatabaseManager:
    """Main database manager class"""
    
    def __init__(self):
        self.supabase = supabase
        if not self.supabase:
            raise ValueError("Supabase client not initialized")
    
    # Allowlist Management
    def is_user_allowlisted(self, phone_number: str) -> bool:
        """Check if a user is in the allowlist"""
        try:
            response = self.supabase.table('allowlist').select('*').eq('phone_number', phone_number).eq('is_active', True).execute()
            return len(response.data) > 0
        except Exception as e:
            logger.error(f"Error checking allowlist for {phone_number}: {e}")
            return False
    
    def add_to_allowlist(self, phone_number: str, name: str = "", email: str = "", notes: str = "") -> bool:
        """Add a user to the allowlist"""
        try:
            data = {
                'phone_number': phone_number,
                'name': name,
                'email': email,
                'notes': notes,
                'is_active': True
            }
            self.supabase.table('allowlist').insert(data).execute()
            logger.info(f"Added {phone_number} to allowlist")
            return True
        except Exception as e:
            logger.error(f"Error adding {phone_number} to allowlist: {e}")
            return False
    
    def get_allowlist(self) -> List[Dict]:
        """Get all allowlisted users"""
        try:
            response = self.supabase.table('allowlist').select('*').eq('is_active', True).execute()
            return response.data
        except Exception as e:
            logger.error(f"Error fetching allowlist: {e}")
            return []
    
    def remove_from_allowlist(self, phone_number: str) -> bool:
        """Remove a user from the allowlist by setting is_active to False"""
        try:
            # Update the user's is_active status to False instead of deleting
            response = self.supabase.table('allowlist').update({'is_active': False}).eq('phone_number', phone_number).execute()
            if response.data:
                logger.info(f"Removed {phone_number} from allowlist")
                return True
            else:
                logger.warning(f"User {phone_number} not found in allowlist")
                return False
        except Exception as e:
            logger.error(f"Error removing {phone_number} from allowlist: {e}")
            return False
    
    # Consent Management
    def check_user_consent(self, phone_number: str) -> Tuple[bool, bool]:
        """Check if user has given privacy and ToS consent"""
        try:
            response = (
                self.supabase.table("user_consent")
                .select("privacy_consent, terms_accepted, is_phone_verified")
                .eq("phone_number", phone_number)
                .limit(1)
                .execute()
            )
            logger.info(f"phone_number : {repr(phone_number)}, user consent: {response.data}")

            if response.data:
                row = response.data[0]
                return row["privacy_consent"], row["terms_accepted"], row["is_phone_verified"]
            return False, False, False
        except Exception as e:
            logger.error(f"Error checking user consent: {e}")
            return False, False, False
    
    # Usage Tracking
    def check_usage_limit(self, phone_number: str) -> UsageInfo:
        """Check if user can make a request based on usage limits"""
        try:
            # Call the stored procedure
            result = self.supabase.rpc('check_and_increment_usage', {'user_phone': phone_number}).execute()
            
            if result.data:
                data = result.data
                
                # Parse time_until_reset - it might be a string like "23:45:30" or an integer
                time_until_reset_raw = data.get('time_until_reset', 86400)
                
                if isinstance(time_until_reset_raw, str):
                    # Parse PostgreSQL interval string format (e.g., "23:45:30")
                    parts = time_until_reset_raw.split(':')
                    if len(parts) == 3:
                        hours = int(parts[0])
                        minutes = int(parts[1])
                        seconds = float(parts[2])
                        total_seconds = hours * 3600 + minutes * 60 + seconds
                    else:
                        # Fallback to 24 hours if format is unexpected
                        total_seconds = 86400
                elif isinstance(time_until_reset_raw, (int, float)):
                    total_seconds = time_until_reset_raw
                else:
                    # Default to 24 hours if type is unexpected
                    total_seconds = 86400
                
                return UsageInfo(
                    can_proceed=data.get('can_proceed', False),
                    current_count=data.get('current_count', 0),
                    daily_limit=data.get('daily_limit', 100), # TODO: Phase 1 MVP - Revert to 10 after Phase 1
                    time_until_reset=timedelta(seconds=total_seconds)
                )
            else:
                # Fallback if stored procedure fails
                return self._manual_usage_check(phone_number)
                
        except Exception as e:
            logger.error(f"Error checking usage for {phone_number}: {e}")
            # Fallback to manual check
            return self._manual_usage_check(phone_number)
    
    def _manual_usage_check(self, phone_number: str) -> UsageInfo:
        """Manual usage check as fallback"""
        try:
            today = date.today()
            
            # Get current usage
            response = self.supabase.table('usage_tracking')\
                .select('*')\
                .eq('phone_number', phone_number)\
                .eq('usage_date', today.isoformat())\
                .execute()
            
            if response.data:
                usage = response.data[0]
                current_count = usage['image_count']
                daily_limit = usage['daily_limit']
            else:
                # Create new usage record
                data = {
                    'phone_number': phone_number,
                    'usage_date': today.isoformat(),
                    'image_count': 0,
                    'daily_limit': 100 # TODO: Phase 1 MVP - Revert to 10 after Phase 1
                }
                self.supabase.table('usage_tracking').insert(data).execute()
                current_count = 0
                daily_limit = 100 # TODO: Phase 1 MVP - Revert to 10 after Phase 1
            
            can_proceed = current_count < daily_limit
            
            # If can proceed, increment count
            if can_proceed:
                self.supabase.table('usage_tracking')\
                    .update({'image_count': current_count + 1, 'last_request_at': datetime.utcnow().isoformat()})\
                    .eq('phone_number', phone_number)\
                    .eq('usage_date', today.isoformat())\
                    .execute()
                current_count += 1
            
            # Calculate time until reset (next midnight)
            tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time())
            time_until_reset = tomorrow - datetime.now()
            
            return UsageInfo(
                can_proceed=can_proceed,
                current_count=current_count,
                daily_limit=daily_limit,
                time_until_reset=time_until_reset
            )
            
        except Exception as e:
            logger.error(f"Manual usage check failed for {phone_number}: {e}")
            return UsageInfo(
                can_proceed=False,
                current_count=100, # TODO: Phase 1 MVP - Revert to 10 after Phase 1
                daily_limit=100, # TODO: Phase 1 MVP - Revert to 10 after Phase 1
                time_until_reset=timedelta(hours=24)
            )
    
    # Submission Management
    def create_submission(self, submission: UserSubmission) -> Optional[str]:
        """Create a new user submission record
        
        Handles both single and multiple images:
        - Single image: stores as string (backward compatible)
        - Multiple images: stores as JSON array
        """
        try:
            # Handle image_url - convert list to JSON if multiple images
            image_url_value = submission.image_url
            if isinstance(image_url_value, list):
                image_url_value = json.dumps(image_url_value)
            
            # Handle s3_key - convert list to JSON if multiple images
            s3_key_value = submission.s3_key
            if isinstance(s3_key_value, list):
                s3_key_value = json.dumps(s3_key_value)
            
            data = {
                'phone_number': submission.phone_number,
                'image_url': image_url_value,
                's3_key': s3_key_value,
                'prediction_result': submission.prediction_result,
                'confidence_score': submission.confidence_score,
                'scam_label': submission.scam_label,
                'processing_time_ms': submission.processing_time_ms,
                'input_text': submission.input_text,
                'message_id': submission.message_id
            }
            
            response = self.supabase.table(get_table_name('b2b_pilot_user_submissions')).insert(data).execute()
            if response.data:
                logger.info(f"Created submission for {submission.phone_number}")
                return response.data[0]['id']
            return None
            
        except Exception as e:
            logger.error(f"Error creating submission: {e}")
            return None
    
    def get_submission_by_id(self, submission_id: str) -> Optional[Dict]:
        """Get a submission by its ID"""
        try:
            response = self.supabase.table(get_table_name('b2b_pilot_user_submissions'))\
                .select('*')\
                .eq('id', submission_id)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            logger.error(f"Error fetching submission {submission_id}: {e}")
            return None
    
    def get_submission_by_message_id(self, message_id: str) -> Optional[Dict]:
        """Get a submission by its message_id (for idempotency check)"""
        try:
            response = self.supabase.table(get_table_name('b2b_pilot_user_submissions'))\
                .select('*')\
                .eq('message_id', message_id)\
                .limit(1)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            logger.error(f"Error fetching submission by message_id {message_id}: {e}")
            return None
    
    def get_latest_submission_without_feedback(self, phone_number: str) -> Optional[Dict]:
        """Get the latest submission for a phone number that doesn't have feedback yet"""
        try:
            response = self.supabase.table(get_table_name('b2b_pilot_user_submissions'))\
                .select('*')\
                .eq('phone_number', phone_number)\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            logger.error(f"Error fetching latest submission for {phone_number}: {e}")
            return None
    
    def update_submission_feedback(self, submission_id: str, rating: int, feedback_text: str = "") -> bool:
        """Update submission with feedback"""
        try:
            data = {
                'feedback_text': feedback_text,
                'feedback_timestamp': datetime.utcnow().isoformat()
            }
            
            self.supabase.table(get_table_name('b2b_pilot_user_submissions'))\
                .update(data)\
                .eq('id', submission_id)\
                .execute()
            
            logger.info(f"Updated feedback for submission {submission_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating feedback: {e}")
            return False
    
    # Subscription Management
    def get_user_subscription(self, phone_number: str) -> Optional[Dict]:
        """Get user's subscription details"""
        try:
            response = self.supabase.table('subscriptions')\
                .select('*')\
                .eq('phone_number', phone_number)\
                .eq('payment_status', 'active')\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            logger.error(f"Error fetching subscription for {phone_number}: {e}")
            return None
    
    def create_subscription(self, phone_number: str, subscription_type: str = 'premium', 
                          daily_limit: int = 100, amount_paid: float = 0.0) -> bool:
        """Create or update user subscription"""
        try:
            data = {
                'phone_number': phone_number,
                'subscription_type': subscription_type,
                'daily_limit': daily_limit,
                'payment_status': 'active',
                'amount_paid': amount_paid,
                'start_date': datetime.utcnow().isoformat(),
                'end_date': (datetime.utcnow() + timedelta(days=30)).isoformat()  # 30-day subscription
            }
            
            # Upsert subscription
            self.supabase.table('subscriptions').upsert(data).execute()
            logger.info(f"Created/updated subscription for {phone_number}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            return False
    
    # Analytics
    def get_analytics_summary(self, start_date: date, end_date: date) -> List[AnalyticsSummary]:
        """Get analytics summary for date range"""
        try:
            response = self.supabase.table('analytics_summary')\
                .select('*')\
                .gte('date', start_date.isoformat())\
                .lte('date', end_date.isoformat())\
                .order('date')\
                .execute()
            
            summaries = []
            for data in response.data:
                summary = AnalyticsSummary(
                    date=datetime.fromisoformat(data['date']).date(),
                    total_submissions=data['total_submissions'],
                    scam_detected=data['scam_detected'],
                    not_scam_detected=data['not_scam_detected'],
                    likely_scam_detected=data['likely_scam_detected'],
                    unique_users=data['unique_users'],
                    users_hit_limit=data['users_hit_limit'],
                    avg_confidence_score=data['avg_confidence_score'],
                    avg_processing_time_ms=data['avg_processing_time_ms'],
                    feedback_count=data['feedback_count']
                )
                summaries.append(summary)
            
            return summaries
            
        except Exception as e:
            logger.error(f"Error fetching analytics: {e}")
            return []
    
    def update_analytics(self, target_date: date = None) -> bool:
        """Update analytics summary for a specific date"""
        try:
            if target_date is None:
                target_date = date.today()
            
            self.supabase.rpc('update_daily_analytics', {'target_date': target_date.isoformat()}).execute()
            logger.info(f"Updated analytics for {target_date}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating analytics: {e}")
            return False
    
    # Feedback Management
    def create_feedback(self, submission_id: str, phone_number: str, rating: int, 
                       feedback_text: str = "", would_recommend: bool = None) -> bool:
        """Create feedback record"""
        try:
            data = {
                'submission_id': submission_id,
                'phone_number': phone_number,
                'rating': rating,
                'feedback_text': feedback_text,
                'would_recommend': would_recommend
            }
            
            self.supabase.table('feedback').insert(data).execute()
            
            # Also update the submission record
            self.update_submission_feedback(submission_id, rating, feedback_text)
            
            logger.info(f"Created feedback for submission {submission_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating feedback: {e}")
            return False
    
    # Utility Methods
    def get_recent_submissions(self, phone_number: str, limit: int = 10) -> List[Dict]:
        """Get recent submissions for a user"""
        try:
            response = self.supabase.table(get_table_name('b2b_pilot_user_submissions'))\
                .select('*')\
                .eq('phone_number', phone_number)\
                .order('created_at', desc=True)\
                .limit(limit)\
                .execute()
            
            return response.data
            
        except Exception as e:
            logger.error(f"Error fetching recent submissions: {e}")
            return []
    
    def get_user_stats(self, phone_number: str) -> Dict:
        """Get comprehensive stats for a user"""
        try:
            # Get submission stats
            submissions = self.supabase.table(get_table_name('b2b_pilot_user_submissions'))\
                .select('*')\
                .eq('phone_number', phone_number)\
                .execute()
            
            # Get usage stats
            today = date.today()
            usage = self.supabase.table('usage_tracking')\
                .select('*')\
                .eq('phone_number', phone_number)\
                .eq('usage_date', today.isoformat())\
                .execute()
            
            # Get subscription
            subscription = self.get_user_subscription(phone_number)
            
            stats = {
                'total_submissions': len(submissions.data),
                'scam_detected': len([s for s in submissions.data if s.get('scam_label') == 'Scam']),
                'today_usage': usage.data[0]['image_count'] if usage.data else 0,
                'daily_limit': usage.data[0]['daily_limit'] if usage.data else 100,  # TODO: Phase 1 MVP - Revert to 10 after Phase 1
                'subscription_type': subscription['subscription_type'] if subscription else 'free',
                'is_allowlisted': self.is_user_allowlisted(phone_number)
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {}

# Global database manager instance
db_manager = DatabaseManager()

# Convenience functions
def get_db():
    """Get database manager instance"""
    global db_manager
    
    if db_manager is None:
        init_database()
    
    return db_manager

def init_database():
    """Initialize database connection"""
    global db_manager
    try:
        db_manager = DatabaseManager()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise e
