"""
Configuration settings for LMS application with HLS support
"""
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # MongoDB
    MONGO_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "lms_database"
    
    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_SECURE: bool = False
    
    # Buckets
    VIDEO_BUCKET: str = "stream-lms-videos"
    THUMBNAIL_BUCKET: str = "stream-lms-thumbnails"
    HLS_BUCKET: str = "stream-lms-hls"
    
    # Redis for Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # HLS Settings
    HLS_SEGMENT_DURATION: int = 4  # seconds
    # HLS_QUALITIES: list = ["360p", "480p", "720p", "1080p"]
    HLS_QUALITIES: list = ["480p", "720p"]

    
    # Video Processing
    TEMP_UPLOAD_DIR: str = "/tmp/lms_uploads"
    
    # API
    API_TITLE: str = "LMS API with HLS"
    API_VERSION: str = "2.0.0"
    
    # CORS
    CORS_ORIGINS: list = ["*"]

    # Base URL for HLS playback (MinIO endpoint or CDN)
    HLS_BASE_URL: str = "http://localhost:9000/stream-lms-hls"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

# Video quality settings for HLS
VIDEO_QUALITIES = {
    "360p": {"width": 640, "height": 360, "bitrate": "800k"},
    "480p": {"width": 854, "height": 480, "bitrate": "1400k"},
    "720p": {"width": 1280, "height": 720, "bitrate": "2800k"},
    "1080p": {"width": 1920, "height": 1080, "bitrate": "5000k"},
}