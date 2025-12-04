
from datetime import timedelta
from minio.error import S3Error
from fastapi import HTTPException
from db_clients import minio_client

def serialize_doc(doc):
    """Convert MongoDB document to JSON serializable format"""
    if doc:
        doc["id"] = str(doc.pop("_id"))
        return doc
    return None

def generate_presigned_url(bucket: str, object_name: str, expires: int = 3600) -> str:
    """
    Generate presigned URL for secure streaming
    
    Args:
        bucket: MinIO bucket name
        object_name: Object path in bucket
        expires: URL expiry time in seconds
    
    Returns:
        Presigned URL string
    """
    try:
        return minio_client.presigned_get_object(
            bucket, 
            object_name, 
            expires=timedelta(seconds=expires)
        )
    except S3Error as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to generate URL: {str(e)}"
        )