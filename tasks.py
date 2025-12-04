# fastapi_hls_tasks.py
import os
import tempfile
import shutil
import logging
from datetime import datetime
from bson import ObjectId
from fastapi import FastAPI, BackgroundTasks
from db_clients import db, minio_client
from hls_processor import hls_processor
from config import settings

logger = logging.getLogger(__name__)
app = FastAPI()


def process_video_to_hls(video_id: str, video_object_name: str):
    temp_dir = tempfile.mkdtemp()
    try:
        temp_video_path = os.path.join(temp_dir, "input_video.mp4")
        hls_output_dir = os.path.join(temp_dir, "hls_output")
        os.makedirs(hls_output_dir, exist_ok=True)

        # Update DB status
        db.videos.update_one(
            {"_id": ObjectId(video_id)},
            {"$set": {"processing_status": "processing", "updated_at": datetime.utcnow()}}
        )

        # Download from MinIO
        minio_client.fget_object(
            settings.VIDEO_BUCKET,
            video_object_name,
            temp_video_path
        )

        # Convert to HLS
        result = hls_processor.process_video_to_hls(temp_video_path, hls_output_dir, video_id)
        if not result.get("success"):
            raise Exception(result.get("error"))

        # Upload HLS files
        hls_base_path = f"hls/{video_id}"
        uploaded_files = []
        for root, dirs, files in os.walk(hls_output_dir):
            for file in files:
                local_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, hls_output_dir)
                minio_path = f"{hls_base_path}/{relative_path}"
                content_type = 'application/vnd.apple.mpegurl' if file.endswith('.m3u8') else 'video/MP2T'
                minio_client.fput_object(
                    settings.HLS_BUCKET,
                    minio_path,
                    local_path,
                    content_type=content_type
                )
                uploaded_files.append(minio_path)

        # Update video doc
        db.videos.update_one(
            {"_id": ObjectId(video_id)},
            {"$set": {
                "video_type": "hls",
                "hls_master_playlist": f"{hls_base_path}/master.m3u8",
                "processing_status": "completed",
                "updated_at": datetime.utcnow()
            }}
        )
        logger.info(f"HLS processing completed for video {video_id}. Uploaded {len(uploaded_files)} files.")

    except Exception as e:
        logger.error(f"HLS processing failed for {video_id}: {str(e)}")
        db.videos.update_one(
            {"_id": ObjectId(video_id)},
            {"$set": {"processing_status": "failed", "processing_error": str(e), "updated_at": datetime.utcnow()}}
        )

    finally:
        shutil.rmtree(temp_dir)
        logger.info(f"Cleaned up temporary files for video {video_id}")