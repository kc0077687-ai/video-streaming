"""
Database and storage client initialization
"""
from motor.motor_asyncio import AsyncIOMotorClient
from minio import Minio
from minio.error import S3Error
from config import settings
import logging

logger = logging.getLogger(__name__)

# MongoDB client
db_client = AsyncIOMotorClient(settings.MONGO_URL)
db = db_client[settings.DATABASE_NAME]

# MinIO client
minio_client = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE
)

def initialize_storage():
    """Initialize MinIO buckets"""
    buckets = [
        settings.VIDEO_BUCKET,
        settings.THUMBNAIL_BUCKET,
        settings.HLS_BUCKET
    ]
    
    for bucket in buckets:
        try:
            if not minio_client.bucket_exists(bucket):
                minio_client.make_bucket(bucket)
                logger.info(f"✅ Created bucket: {bucket}")
            else:
                logger.info(f"✓ Bucket exists: {bucket}")
        except S3Error as e:
            logger.error(f"❌ Failed to create bucket {bucket}: {e}")


