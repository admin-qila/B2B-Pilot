"""
S3 Service for secure image storage in Qila Scam Detection Service
Implements comprehensive security features including encryption, access control, and audit logging
"""

import os
import boto3
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, List, Any
from botocore.exceptions import ClientError
import uuid
from io import BytesIO

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class S3Service:
    """Secure S3 storage service for user-submitted images"""
    
    def __init__(self):
        """Initialize S3 client with security configurations"""
        self.aws_region = os.getenv('AWS_REGION', 'us-east-1')
        self.bucket_name = os.getenv('S3_BUCKET_NAME')
        self.kms_key_id = os.getenv('AWS_KMS_KEY_ID')  # optional

        if not self.bucket_name:
            raise ValueError("S3_BUCKET_NAME is required")

        # Let boto3 auto-pick credentials from IAM role
        self.s3_client = boto3.client('s3', region_name=self.aws_region)
        self.kms_client = boto3.client('kms', region_name=self.aws_region)
        
        logger.info(f"S3 service initialized for bucket: {self.bucket_name}")
    
    def generate_secure_key(self, phone_number: str, submission_id: str) -> str:
        """Generate a secure S3 object key with proper folder structure"""
        # Hash the phone number for privacy
        phone_hash = hashlib.sha256(phone_number.encode()).hexdigest()[:16]
        
        # Extract the actual phone number (remove 'whatsapp:' prefix if present)
        clean_phone = phone_number.replace('whatsapp:', '').replace('+', '').strip()
        
        # Create timestamp components
        now = datetime.utcnow()
        year = now.strftime('%Y')
        month = now.strftime('%m')
        day = now.strftime('%d')
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        milliseconds = now.strftime('%f')[:3]  # First 3 digits of microseconds
        
        # Generate unique identifier
        unique_id = uuid.uuid4().hex[:8]
        
        # Structure: images/phone_hash/year/month/day/timestamp_milliseconds_submission_id_unique.jpg
        # This groups all images by phone number first, then by date for easier management
        key = f"images/{phone_hash}/{year}/{month}/{day}/{timestamp}_{milliseconds}_{submission_id}_{unique_id}.jpg"
        
        return key
    
    def create_presigned_upload_url(self, s3_key: str, 
                                   content_type: str = 'image/jpeg', 
                                   expires_in: int = 300) -> Dict[str, str]:
        """Create a presigned URL for secure direct upload to S3"""
        try:
            # Define base upload conditions
            conditions = [
                {'Content-Type': content_type},
                ['content-length-range', 1, 16 * 1024 * 1024],  # Max 16MB
            ]

            # Only add KMS encryption if key is configured
            if self.kms_key_id:
                conditions.extend([
                    {'x-amz-server-side-encryption': 'aws:kms'},
                    {'x-amz-server-side-encryption-aws-kms-key-id': self.kms_key_id}
                ])
            
            # Remove None conditions
            conditions = [c for c in conditions if c is not None]
            
            # Generate presigned POST URL
            response = self.s3_client.generate_presigned_post(
                Bucket=self.bucket_name,
                Key=s3_key,
                Conditions=conditions,
                ExpiresIn=expires_in
            )
            
            logger.info(f"Generated presigned URL for upload: {s3_key}")
            return response
            
        except ClientError as e:
            logger.error(f"Error generating presigned URL: {e}")
            raise
    
    def upload_image(self, image_data: bytes, phone_number: str, 
                    submission_id: str, content_type: str = 'image/jpeg') -> Tuple[bool, Optional[str]]:
        """
        Upload image to S3 with encryption and metadata
        Returns: (success, s3_key)
        """
        try:
            key = self.generate_secure_key(phone_number, submission_id)
            
            # Prepare metadata
            metadata = {
                'submission_id': submission_id,
                'upload_timestamp': datetime.utcnow().isoformat(),
                'content_type': content_type,
                'phone_hash': hashlib.sha256(phone_number.encode()).hexdigest()
            }
            
            # Calculate content hash for integrity
            content_hash = hashlib.sha256(image_data).hexdigest()
            metadata['content_hash'] = content_hash
            
            # Upload parameters with server-side encryption
            upload_params = {
                'Bucket': self.bucket_name,
                'Key': key,
                'Body': image_data,
                'ContentType': content_type,
                'Metadata': metadata,
                'ServerSideEncryption': 'aws:kms',
                'StorageClass': 'INTELLIGENT_TIERING',  # Optimize storage costs
                'ContentDisposition': 'attachment',  # Force download, not display
            }
            
            # Add KMS key if available
            if self.kms_key_id:
                upload_params['SSEKMSKeyId'] = self.kms_key_id
            
            # Add object lock if enabled (for compliance)
            if os.environ.get('S3_OBJECT_LOCK_ENABLED', 'false').lower() == 'true':
                upload_params['ObjectLockMode'] = 'COMPLIANCE'
                upload_params['ObjectLockRetainUntilDate'] = (
                    datetime.utcnow() + timedelta(days=int(os.environ.get('S3_RETENTION_DAYS', '90')))
                )
            
            # Upload to S3
            response = self.s3_client.put_object(**upload_params)
            
            # Verify upload integrity
            if response.get('ETag'):
                logger.info(f"Successfully uploaded image to S3: {key}")
                
                return True, key
            else:
                logger.error("Upload verification failed - no ETag received")
                return False, None
                
        except ClientError as e:
            logger.error(f"S3 upload error: {e}")
            return False, None
        except Exception as e:
            logger.error(f"Unexpected error during upload: {e}")
            return False, None
    
    def create_presigned_download_url(self, s3_key: str, expires_in: int = 3600) -> Optional[str]:
        """Create a time-limited presigned URL for secure image access"""
        try:
            # Generate presigned URL
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': s3_key,
                    'ResponseContentDisposition': 'attachment'  # Force download
                },
                ExpiresIn=expires_in
            )
            
            logger.info(f"Generated presigned download URL for: {s3_key}")
            return url
            
        except ClientError as e:
            logger.error(f"Error generating download URL: {e}")
            return None
    
    def delete_image(self, s3_key: str, verify_before_delete: bool = True) -> bool:
        """Securely delete an image from S3 with optional verification"""
        try:
            if verify_before_delete:
                # Verify object exists before deletion
                try:
                    self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
                except ClientError as e:
                    if e.response['Error']['Code'] == '404':
                        logger.warning(f"Object not found for deletion: {s3_key}")
                        return False
                    raise
            
            # Delete the object
            response = self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            # Check if deletion was successful
            if response['ResponseMetadata']['HTTPStatusCode'] == 204:
                logger.info(f"Successfully deleted image from S3: {s3_key}")
                return True
            else:
                logger.error(f"Unexpected response code during deletion: {response}")
                return False
                
        except ClientError as e:
            logger.error(f"Error deleting image from S3: {e}")
            return False
    
    def get_object_metadata(self, s3_key: str) -> Optional[Dict]:
        """Retrieve object metadata for audit and verification"""
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            metadata = {
                'size': response.get('ContentLength'),
                'content_type': response.get('ContentType'),
                'last_modified': response.get('LastModified'),
                'etag': response.get('ETag'),
                'encryption': response.get('ServerSideEncryption'),
                'metadata': response.get('Metadata', {}),
                'storage_class': response.get('StorageClass')
            }
            
            return metadata
            
        except ClientError as e:
            logger.error(f"Error retrieving object metadata: {e}")
            return None
    
    def create_bucket_lifecycle_policy(self):
        """Create lifecycle policy for automatic data management"""
        lifecycle_policy = {
            'Rules': [
                {
                    'ID': 'ArchiveOldSubmissions',
                    'Status': 'Enabled',
                    'Filter': {'Prefix': 'images/'},
                    'Transitions': [
                        {
                            'Days': 30,
                            'StorageClass': 'STANDARD_IA'
                        },
                        {
                            'Days': 90,
                            'StorageClass': 'GLACIER'
                        }
                    ]
                },
                {
                    'ID': 'DeleteOldSubmissions',
                    'Status': 'Enabled',
                    'Filter': {
                        'Tag': {
                            'Key': 'Retention',
                            'Value': 'Standard'
                        }
                    },
                    'Expiration': {
                        'Days': 365  # Delete after 1 year
                    }
                }
            ]
        }
        
        try:
            self.s3_client.put_bucket_lifecycle_configuration(
                Bucket=self.bucket_name,
                LifecycleConfiguration=lifecycle_policy
            )
            logger.info("Lifecycle policy created successfully")
            return True
        except ClientError as e:
            logger.error(f"Error creating lifecycle policy: {e}")
            return False
    
    def enable_bucket_versioning(self):
        """Enable versioning for additional data protection"""
        try:
            self.s3_client.put_bucket_versioning(
                Bucket=self.bucket_name,
                VersioningConfiguration={'Status': 'Enabled'}
            )
            logger.info("Bucket versioning enabled")
            return True
        except ClientError as e:
            logger.error(f"Error enabling versioning: {e}")
            return False
    
    def create_bucket_encryption_policy(self):
        """Apply default encryption to all objects in the bucket"""
        encryption_config = {
            'Rules': [{
                'ApplyServerSideEncryptionByDefault': {
                    'SSEAlgorithm': 'aws:kms',
                    'KMSMasterKeyID': self.kms_key_id
                } if self.kms_key_id else {
                    'SSEAlgorithm': 'AES256'
                }
            }]
        }
        
        try:
            self.s3_client.put_bucket_encryption(
                Bucket=self.bucket_name,
                ServerSideEncryptionConfiguration=encryption_config
            )
            logger.info("Bucket encryption policy applied")
            return True
        except ClientError as e:
            logger.error(f"Error setting encryption policy: {e}")
            return False
    
    def enable_bucket_logging(self, logging_bucket: Optional[str] = None):
        """Enable access logging for audit trail"""
        if not logging_bucket:
            logging_bucket = f"{self.bucket_name}-logs"
        
        try:
            self.s3_client.put_bucket_logging(
                Bucket=self.bucket_name,
                BucketLoggingStatus={
                    'LoggingEnabled': {
                        'TargetBucket': logging_bucket,
                        'TargetPrefix': f"{self.bucket_name}/access-logs/"
                    }
                }
            )
            logger.info(f"Access logging enabled to bucket: {logging_bucket}")
            return True
        except ClientError as e:
            logger.error(f"Error enabling logging: {e}")
            return False
    
    def list_user_images(self, phone_number: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """List all images for a specific phone number"""
        try:
            # Hash the phone number to get the folder prefix
            phone_hash = hashlib.sha256(phone_number.encode()).hexdigest()[:16]
            prefix = f"images/{phone_hash}/"
            
            # List objects with the prefix
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=prefix,
                PaginationConfig={'MaxItems': max_results}
            )
            
            images = []
            for page in page_iterator:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        # Parse the key to extract metadata
                        key_parts = obj['Key'].split('/')
                        if len(key_parts) >= 6:  # images/phone_hash/year/month/day/filename
                            filename = key_parts[-1]
                            year = key_parts[2]
                            month = key_parts[3]
                            day = key_parts[4]
                            
                            # Extract timestamp from filename
                            filename_parts = filename.split('_')
                            if len(filename_parts) >= 4:
                                date_str = filename_parts[0]
                                time_str = filename_parts[1]
                                milliseconds = filename_parts[2]
                                submission_id = filename_parts[3]
                                
                                images.append({
                                    'key': obj['Key'],
                                    'size': obj['Size'],
                                    'last_modified': obj['LastModified'],
                                    'year': year,
                                    'month': month,
                                    'day': day,
                                    'date': date_str,
                                    'time': time_str,
                                    'milliseconds': milliseconds,
                                    'submission_id': submission_id.split('_')[0],  # Remove unique suffix
                                    'etag': obj.get('ETag', '').strip('"')
                                })
            
            # Sort by last modified date (newest first)
            images.sort(key=lambda x: x['last_modified'], reverse=True)
            
            logger.info(f"Listed {len(images)} images for phone hash: {phone_hash}")
            return images
            
        except ClientError as e:
            logger.error(f"Error listing user images: {e}")
            return []
    
    def get_user_storage_stats(self, phone_number: str) -> Dict[str, Any]:
        """Get storage statistics for a specific user"""
        try:
            images = self.list_user_images(phone_number, max_results=1000)
            
            total_size = sum(img['size'] for img in images)
            total_count = len(images)
            
            # Group by year/month
            by_month = {}
            by_day = {}
            
            for img in images:
                month_key = f"{img['year']}-{img['month']}"
                day_key = f"{img['year']}-{img['month']}-{img['day']}"
                
                if month_key not in by_month:
                    by_month[month_key] = {'count': 0, 'size': 0}
                by_month[month_key]['count'] += 1
                by_month[month_key]['size'] += img['size']
                
                if day_key not in by_day:
                    by_day[day_key] = {'count': 0, 'size': 0}
                by_day[day_key]['count'] += 1
                by_day[day_key]['size'] += img['size']
            
            stats = {
                'total_images': total_count,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'total_size_gb': round(total_size / (1024 * 1024 * 1024), 3),
                'by_month': by_month,
                'by_day': by_day,
                'oldest_image': images[-1]['last_modified'] if images else None,
                'newest_image': images[0]['last_modified'] if images else None,
                'average_size_mb': round((total_size / total_count) / (1024 * 1024), 2) if total_count > 0 else 0
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting user storage stats: {e}")
            return {
                'total_images': 0,
                'total_size_bytes': 0,
                'total_size_mb': 0,
                'error': str(e)
            }
    
    def delete_user_images(self, phone_number: str, older_than_days: Optional[int] = None) -> Dict[str, Any]:
        """Delete all images for a user, optionally filtering by age"""
        try:
            images = self.list_user_images(phone_number, max_results=1000)
            
            if older_than_days:
                cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
                images = [img for img in images if img['last_modified'].replace(tzinfo=None) < cutoff_date]
            
            deleted_count = 0
            failed_count = 0
            total_size_deleted = 0
            
            for img in images:
                if self.delete_image(img['key'], verify_before_delete=False):
                    deleted_count += 1
                    total_size_deleted += img['size']
                else:
                    failed_count += 1
            
            result = {
                'deleted_count': deleted_count,
                'failed_count': failed_count,
                'total_size_deleted_mb': round(total_size_deleted / (1024 * 1024), 2),
                'older_than_days': older_than_days
            }
            
            logger.info(f"Deleted {deleted_count} images for user, {failed_count} failed")
            return result
            
        except Exception as e:
            logger.error(f"Error deleting user images: {e}")
            return {
                'deleted_count': 0,
                'failed_count': 0,
                'error': str(e)
            }
    
    def get_image_url_by_submission(self, submission_id: str, phone_number: str) -> Optional[str]:
        """Get presigned URL for an image by submission ID"""
        try:
            # List user images and find the one with matching submission ID
            images = self.list_user_images(phone_number)
            
            for img in images:
                if submission_id in img.get('submission_id', ''):
                    return self.create_presigned_download_url(img['key'])
            
            logger.warning(f"No image found for submission ID: {submission_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting image URL by submission: {e}")
            return None

# Create global S3 service instance
s3_service = None

def get_s3_service() -> S3Service:
    """Get or create S3 service instance"""
    global s3_service
    if s3_service is None:
        s3_service = S3Service()
    return s3_service
