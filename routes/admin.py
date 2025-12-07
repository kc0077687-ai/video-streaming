"""
Admin API routes with HLS processing support
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from datetime import datetime,timezone
from typing import Optional
from bson import ObjectId
from fastapi import UploadFile
import tempfile
import aiofiles
from minio import Minio
import asyncio
import io
from minio.error import S3Error

import io

from db_clients import db, minio_client
from models import CourseCreate, CourseResponse, ChapterCreate, ChapterResponse
from helpers import serialize_doc, generate_presigned_url
from config import settings

from tasks import process_video_to_hls_task


from concurrent.futures import ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=5)

admin_router = APIRouter(prefix="/admin", tags=["Admin"])


@admin_router.post("/courses", response_model=CourseResponse)
async def create_course(course: CourseCreate):
    """Create a new course"""
    course_doc = {
        **course.model_dump(),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = await db.courses.insert_one(course_doc)
    
    return CourseResponse(
        id=str(result.inserted_id),
        title=course.title,
        description=course.description,
        instructor=course.instructor,
        created_at=course_doc["created_at"],
        chapter_count=0
    )

@admin_router.get("/courses")
async def list_courses():
    """List all courses with chapter counts"""
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

@admin_router.delete("/courses/{course_id}")
async def delete_course(course_id: str):
    """Delete a course"""
    result = await db.courses.delete_one({"_id": ObjectId(course_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Course not found")
    return {"message": "Course deleted successfully"}



@admin_router.post("/chapters", response_model=ChapterResponse)
async def create_chapter(chapter: ChapterCreate):
    """Create a new chapter"""
    try:
        course = await db.courses.find_one({"_id": ObjectId(chapter.course_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid course ID format")
    
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    
    chapter_doc = {
        **chapter.model_dump(),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    
    result = await db.chapters.insert_one(chapter_doc)
    
    return ChapterResponse(
        id=str(result.inserted_id),
        course_id=chapter.course_id,
        title=chapter.title,
        description=chapter.description,
        order=chapter.order,
        video_count=0,
        created_at=chapter_doc["created_at"]
    )

@admin_router.get("/courses/{course_id}/chapters")
async def list_chapters(course_id: str):
    """List all chapters in a course"""
    chapters = []
    async for chapter in db.chapters.find({"course_id": course_id}).sort("order", 1):
        video_count = await db.videos.count_documents({
            "chapter_id": str(chapter["_id"])
        })
        chapters.append({
            **serialize_doc(chapter),
            "video_count": video_count
        })
    return chapters

@admin_router.delete("/chapters/{chapter_id}")
async def delete_chapter(chapter_id: str):
    """Delete a chapter"""
    result = await db.chapters.delete_one({"_id": ObjectId(chapter_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {"message": "Chapter deleted successfully"}


# async def upload_file_multipart(bucket_name: str, object_name: str, upload_file: UploadFile):
#     """
#     Save UploadFile to a temp file and upload to MinIO (handles multipart automatically)
#     """
#     suffix = upload_file.filename.split(".")[-1] if "." in upload_file.filename else "mp4"
#     async with aiofiles.tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as tmp:
#         while True:
#             chunk = await upload_file.read(10*1024*1024)  # 1MB chunks
#             if not chunk:
#                 break
#             await tmp.write(chunk)
#         tmp_path = tmp.name

#     # Upload using MinIO fput_object (multipart is automatic)
#     minio_client.fput_object(
#         bucket_name,
#         object_name,
#         tmp_path,
#         content_type=upload_file.content_type or "video/mp4"
#     )


async def upload_file_stream(bucket_name: str, object_name: str,
                             upload_file: UploadFile, minio_client: Minio):

    loop = asyncio.get_running_loop()
    chunk_size = 5 * 1024 * 1024  

    async def async_reader():
        """Async generator reading upload file in chunks."""
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            yield chunk

    class SyncStream(io.RawIOBase):
        """
        Sync file-like object wrapper so MinIO can read from async data.
        """

        def __init__(self):
            self._agen = async_reader()
            self._buffer = b""

        def readable(self):
            return True

        def read(self, n=-1):
            """
            MinIO calls this synchronously.
            We fetch async chunks using run_coroutine_threadsafe.
            """
            while len(self._buffer) < n or n == -1:
                try:
                    next_chunk = asyncio.run_coroutine_threadsafe(
                        self._agen.__anext__(), loop
                    ).result()
                except StopAsyncIteration:
                    break

                self._buffer += next_chunk

                if n == -1:
                    break

            if n == -1:
                chunk, self._buffer = self._buffer, b""
                return chunk

            chunk, self._buffer = self._buffer[:n], self._buffer[n:]
            return chunk

    stream = SyncStream()

    def run_minio_upload():
        minio_client.put_object(
            bucket_name=bucket_name,
            object_name=object_name,
            data=stream,
            length=-1,                    
            part_size=5 * 1024 * 1024,     
            content_type=upload_file.content_type or "video/mp4",
        )

    # run in thread so MinIO never blocks event loop
    await loop.run_in_executor(executor, run_minio_upload)

    print("Upload complete!")




@admin_router.post("/videos/upload")
async def upload_video_with_hls(
    chapter_id: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    order: int = Form(...),
    duration: Optional[int] = Form(None),
    enable_hls: bool = Form(True),
    video_file: UploadFile = File(...),
    thumbnail_file: Optional[UploadFile] = File(None)
):
    """
    Upload video with HLS processing
    - If enable_hls=True: Video will be converted to HLS format in background
    - If enable_hls=False: Video uploaded as-is (legacy support)
    """
    try:
        chapter = await db.chapters.find_one({"_id": ObjectId(chapter_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chapter ID format")
    
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    # Generate unique object names
    now = datetime.now(timezone.utc)
    timestamp = int(now.timestamp())
    file_ext = video_file.filename.split(".")[-1] if "." in video_file.filename else "mp4"
    video_object_name = f"videos/{chapter_id}/{timestamp}.{file_ext}"
    
    # Upload original video to MinIO
    # video_data = await video_file.read()
    # minio_client.put_object(
    #     settings.VIDEO_BUCKET,
    #     video_object_name,
    #     io.BytesIO(video_data),
    #     length=len(video_data),
    #     content_type=video_file.content_type or "video/mp4"
    # )

    await upload_file_stream(settings.VIDEO_BUCKET, video_object_name, video_file,minio_client)

    
    # Upload thumbnail if provided
    thumbnail_object_name = None
    if thumbnail_file:
        thumb_ext = thumbnail_file.filename.split(".")[-1] if "." in thumbnail_file.filename else "jpg"
        thumbnail_object_name = f"thumbnails/{chapter_id}/{timestamp}.{thumb_ext}"
        thumb_data = await thumbnail_file.read()
        minio_client.put_object(
            settings.THUMBNAIL_BUCKET,
            thumbnail_object_name,
            io.BytesIO(thumb_data),
            length=len(thumb_data),
            content_type=thumbnail_file.content_type or "image/jpeg"
        )
    
    # Create video record
    video_doc = {
        "chapter_id": chapter_id,
        "title": title,
        "description": description,
        "order": order,
        "duration": duration,
        "video_type": "hls" if enable_hls else "uploaded",
        "video_object_name": video_object_name,
        "thumbnail_object_name": thumbnail_object_name,
        "youtube_url": None,
        "hls_master_playlist": None,
        "processing_status": "pending" if enable_hls else "completed",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = await db.videos.insert_one(video_doc)
    video_id = str(result.inserted_id)
    
    # if enable_hls:
    #     background_tasks.add_task(
    #         process_video_to_hls,
    #         video_id,
    #         video_object_name
    #     )
    if enable_hls:
        process_video_to_hls_task.delay(video_id, video_object_name)


    return {
        "id": video_id,
        "message": "Video uploaded successfully. HLS processing started." if enable_hls else "Video uploaded successfully.",
        "video_object_name": video_object_name,
        "processing_status": "pending" if enable_hls else "completed"
    }



@admin_router.post("/videos/youtube")
async def add_youtube_video(
    chapter_id: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    order: int = Form(...),
    youtube_url: str = Form(...),
    duration: Optional[int] = Form(None)
):
    """Add a YouTube video link"""
    try:
        chapter = await db.chapters.find_one({"_id": ObjectId(chapter_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chapter ID format")
    
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    # Extract YouTube video ID
    video_id = None
    if "youtube.com" in youtube_url and "v=" in youtube_url:
        video_id = youtube_url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in youtube_url:
        video_id = youtube_url.split("youtu.be/")[1].split("?")[0]
    
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg" if video_id else None
    
    video_doc = {
        "chapter_id": chapter_id,
        "title": title,
        "description": description,
        "order": order,
        "duration": duration,
        "video_type": "youtube",
        "youtube_url": youtube_url,
        "video_object_name": None,
        "thumbnail_object_name": None,
        "thumbnail_url": thumbnail_url,
        "hls_master_playlist": None,
        "processing_status": "completed",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = await db.videos.insert_one(video_doc)
    
    return {
        "id": str(result.inserted_id),
        "message": "YouTube video added successfully",
        "thumbnail_url": thumbnail_url
    }

@admin_router.get("/chapters/{chapter_id}/videos")
async def list_videos_admin(chapter_id: str):
    """List all videos in a chapter with processing status"""
    videos = []
    async for video in db.videos.find({"chapter_id": chapter_id}).sort("order", 1):
        video_data = serialize_doc(video)
        
        # Generate thumbnail URL for uploaded videos
        if video_data.get("video_type") in ["uploaded", "hls"] and video_data.get("thumbnail_object_name"):
            video_data["thumbnail_url"] = generate_presigned_url(
                settings.THUMBNAIL_BUCKET,
                video_data["thumbnail_object_name"],
                expires=86400
            )
        
        videos.append(video_data)
    return videos

@admin_router.get("/videos/{video_id}/status")
async def get_video_processing_status(video_id: str):
    """Get HLS processing status for a video"""
    try:
        video = await db.videos.find_one({"_id": ObjectId(video_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return {
        "video_id": video_id,
        "processing_status": video.get("processing_status", "unknown"),
        "video_type": video.get("video_type"),
        "hls_available": bool(video.get("hls_master_playlist")),
        "error": video.get("processing_error")
    }

@admin_router.delete("/videos/{video_id}")
async def delete_video(video_id: str):
    """Delete a video and its HLS files"""
    try:
        video = await db.videos.find_one({"_id": ObjectId(video_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Delete original video from MinIO
    if video.get("video_object_name"):
        try:
            minio_client.remove_object(settings.VIDEO_BUCKET, video["video_object_name"])
        except Exception as e:
            print(f"Failed to delete video: {e}")
    
    # Delete thumbnail
    if video.get("thumbnail_object_name"):
        try:
            minio_client.remove_object(settings.THUMBNAIL_BUCKET, video["thumbnail_object_name"])
        except Exception as e:
            print(f"Failed to delete thumbnail: {e}")
    
    # Delete HLS files (if any)
    if video.get("hls_master_playlist"):
        hls_base = f"hls/{video_id}/"
        # TODO: Implement recursive deletion of HLS folder
    
    # Delete from database
    await db.videos.delete_one({"_id": ObjectId(video_id)})
    
    return {"message": "Video deleted successfully"}