"""
Pydantic models for request/response validation
"""
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional, List
from bson import ObjectId

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


class CourseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    instructor: Optional[str] = None
    
class CourseResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    instructor: Optional[str]
    created_at: datetime
    chapter_count: int = 0


class ChapterCreate(BaseModel):
    course_id: str
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    order: int = Field(ge=0)

class ChapterResponse(BaseModel):
    id: str
    course_id: str
    title: str
    description: Optional[str]
    order: int
    video_count: int = 0
    created_at: datetime


class VideoCreate(BaseModel):
    chapter_id: str
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    order: int = Field(ge=0)
    duration: Optional[int] = None
    youtube_url: Optional[str] = None

class VideoResponse(BaseModel):
    id: str
    chapter_id: str
    title: str
    description: Optional[str]
    order: int
    duration: Optional[int]
    video_type: str  # 'uploaded', 'youtube', 'hls'
    youtube_url: Optional[str]
    thumbnail_url: Optional[str]
    hls_master_url: Optional[str] = None
    processing_status: Optional[str] = None  # 'pending', 'processing', 'completed', 'failed'
    created_at: datetime


class UserProgress(BaseModel):
    user_id: str
    video_id: str
    progress_seconds: int = Field(ge=0)
    completed: bool = False
    last_watched: Optional[datetime] = None
    
    @field_validator('progress_seconds', mode='before')
    @classmethod
    def convert_progress_to_int(cls, v):
        """Convert float to int if needed"""
        if isinstance(v, float):
            return int(v)
        return v

class ProgressResponse(BaseModel):
    message: str
    acknowledged: bool = True


class HLSProcessingTask(BaseModel):
    video_id: str
    status: str  # 'pending', 'processing', 'completed', 'failed'
    progress: int = 0  # 0-100
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime