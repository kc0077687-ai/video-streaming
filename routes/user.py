"""
User API routes with HLS streaming support
"""
from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from datetime import datetime

from db_clients import db
from models import UserProgress, ProgressResponse
from helpers import serialize_doc, generate_presigned_url
from config import settings

user_router = APIRouter(prefix="/user", tags=["User"])

@user_router.get("/courses")
async def get_user_courses():
    """Get all available courses"""
    courses = []
    async for course in db.courses.find().sort("created_at", -1):
        chapter_count = await db.chapters.count_documents({
            "course_id": str(course["_id"])
        })
        courses.append({
            **serialize_doc(course),
            "chapter_count": chapter_count
        })
    return courses

@user_router.get("/courses/{course_id}/chapters")
async def get_course_chapters(course_id: str, user_id: str = Query(...)):
    """Get all chapters with user progress"""
    chapters = []
    async for chapter in db.chapters.find({"course_id": course_id}).sort("order", 1):
        chapter_data = serialize_doc(chapter)
        
        videos = []
        async for video in db.videos.find({"chapter_id": chapter_data["id"]}).sort("order", 1):
            video_data = serialize_doc(video)
            
            # Get user progress
            progress = await db.user_progress.find_one({
                "user_id": user_id,
                "video_id": video_data["id"]
            })
            
            video_data["user_progress"] = {
                "progress_seconds": progress["progress_seconds"] if progress else 0,
                "completed": progress["completed"] if progress else False
            }
            
            # Generate thumbnail URL
            if video_data.get("video_type") in ["uploaded", "hls"] and video_data.get("thumbnail_object_name"):
                video_data["thumbnail_url"] = generate_presigned_url(
                    settings.THUMBNAIL_BUCKET,
                    video_data["thumbnail_object_name"],
                    expires=86400
                )
            
            videos.append(video_data)
        
        chapter_data["videos"] = videos
        chapters.append(chapter_data)
    
    return chapters

@user_router.get("/videos/{video_id}/stream")
async def stream_video(video_id: str, user_id: str = Query(...)):
    """
    Get streaming URL for a video
    - EARLY HLS: Allow streaming as soon as 360p.m3u8 exists
    - Uploaded MP4: Returns presigned URL
    - YouTube: Returns YouTube data
    """
    # 1) Fetch video
    try:
        video = await db.videos.find_one({"_id": ObjectId(video_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid video ID format")

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video_type = video.get("video_type")

    if video_type == "youtube":
        return {
            "video_type": "youtube",
            "youtube_url": video["youtube_url"],
            "thumbnail_url": video.get("thumbnail_url"),
            "duration": video.get("duration")
        }

    
    if video_type == "hls":
        from helpers import object_exists  # Ensure this helper is added

        master_playlist = video.get("hls_master_playlist")
        if not master_playlist:
            raise HTTPException(status_code=500, detail="Master playlist missing")

        # Extract folder: "676acbbf.../master.m3u8" → "676acbbf..."
        folder = master_playlist.split("/")[0]

        # Lowest quality file path
        lowest_quality_path = f"{folder}/360p.m3u8"

        # Check if 360p is ready
        lowest_ready = object_exists(settings.HLS_BUCKET, lowest_quality_path)

        # Still processing → but not ready for playback
        if not lowest_ready:
            return {
                "video_type": "hls",
                "stream_ready": False,
                "processing_status": video.get("processing_status", "processing"),
                "message": "Video is being processed. Playback not available yet."
            }

        # 360p is ready → allow streaming
        hls_url = generate_presigned_url(
            settings.HLS_BUCKET,
            master_playlist,
            expires=7200
        )

        # Check available qualities
        qualities = {
            "360p": lowest_ready,
            "480p": object_exists(settings.HLS_BUCKET, f"{folder}/480p.m3u8"),
            "720p": object_exists(settings.HLS_BUCKET, f"{folder}/720p.m3u8"),
            "1080p": object_exists(settings.HLS_BUCKET, f"{folder}/1080p.m3u8"),
        }

        thumbnail_url = None
        if video.get("thumbnail_object_name"):
            thumbnail_url = generate_presigned_url(
                settings.THUMBNAIL_BUCKET,
                video["thumbnail_object_name"],
                expires=3600
            )

        return {
            "video_type": "hls",
            "hls_url": hls_url,
            "stream_ready": True,
            "processing_status": video.get("processing_status"),
            "qualities": qualities,
            "thumbnail_url": thumbnail_url,
            "duration": video.get("duration")
        }

   
    stream_url = generate_presigned_url(
        settings.VIDEO_BUCKET,
        video["video_object_name"],
        expires=3600
    )

    thumbnail_url = None
    if video.get("thumbnail_object_name"):
        thumbnail_url = generate_presigned_url(
            settings.THUMBNAIL_BUCKET,
            video["thumbnail_object_name"],
            expires=3600
        )

    return {
        "video_type": "uploaded",
        "stream_url": stream_url,
        "thumbnail_url": thumbnail_url,
        "duration": video.get("duration")
    }


@user_router.post("/progress", response_model=ProgressResponse)
async def update_progress(progress: UserProgress):
    """Update user's video watching progress"""
    try:
        video = await db.videos.find_one({"_id": ObjectId(progress.video_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    progress_doc = {
        "user_id": progress.user_id,
        "video_id": progress.video_id,
        "progress_seconds": progress.progress_seconds,
        "completed": progress.completed,
        "last_watched": datetime.utcnow()
    }
    
    result = await db.user_progress.update_one(
        {"user_id": progress.user_id, "video_id": progress.video_id},
        {"$set": progress_doc},
        upsert=True
    )
    
    return ProgressResponse(
        message="Progress updated successfully",
        acknowledged=result.acknowledged
    )

@user_router.get("/progress/{user_id}")
async def get_user_progress(user_id: str):
    """Get all progress for a user"""
    progress_list = []
    async for progress in db.user_progress.find({"user_id": user_id}):
        progress_list.append(serialize_doc(progress))
    return progress_list