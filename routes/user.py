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
    - HLS videos: Returns master playlist URL
    - Uploaded videos: Returns presigned URL
    - YouTube videos: Returns YouTube URL
    """
    try:
        video = await db.videos.find_one({"_id": ObjectId(video_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    video_type = video.get("video_type")
    
    # YouTube video
    if video_type == "youtube":
        return {
            "video_type": "youtube",
            "youtube_url": video["youtube_url"],
            "thumbnail_url": video.get("thumbnail_url"),
            "duration": video.get("duration")
        }
    
    # HLS video
    elif video_type == "hls":
        processing_status = video.get("processing_status")
        
        # Check if HLS processing is complete
        if processing_status != "completed":
            return {
                "video_type": "hls",
                "processing_status": processing_status,
                "message": "Video is still being processed. Please try again later.",
                "fallback_available": bool(video.get("video_object_name"))
            }
        
        # Generate presigned URL for master playlist
        master_playlist = video.get("hls_master_playlist")
        if not master_playlist:
            raise HTTPException(
                status_code=500, 
                detail="HLS master playlist not found"
            )
        
        hls_url = generate_presigned_url(
            settings.HLS_BUCKET,
            master_playlist,
            expires=7200  # 2 hours for HLS
        )
        
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
            "thumbnail_url": thumbnail_url,
            "duration": video.get("duration"),
            "processing_status": "completed"
        }
    
    # Regular uploaded video (legacy)
    else:
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