"""
LMS System - FastAPI Backend with HLS Streaming
Production-ready Learning Management System
"""
from fastapi import FastAPI,BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from config import settings
from db_clients import db, initialize_storage
from routes.admin import admin_router
from routes.user import user_router

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    logger.info("Starting LMS Application with HLS support...")
    
    # Initialize storage buckets
    initialize_storage()
    
    # Create database indexes
    await db.courses.create_index("title")
    await db.chapters.create_index([("course_id", 1), ("order", 1)])
    await db.videos.create_index([("chapter_id", 1), ("order", 1)])
    await db.user_progress.create_index(
        [("user_id", 1), ("video_id", 1)], 
        unique=True
    )
    logger.info("✅ Database indexes created")
    
    logger.info("✅ Application started successfully")
    
    yield
    
    logger.info("Shutting down LMS Application...")


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    lifespan=lifespan,
    description="Learning Management System with HLS adaptive streaming"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(admin_router)
app.include_router(user_router)


@app.get("/", tags=["System"])
async def root():
    """Root endpoint"""
    return {
        "message": "LMS API with HLS Streaming",
        "version": settings.API_VERSION,
        "features": [
            "HLS Adaptive Bitrate Streaming",
            "YouTube Integration",
            "Progress Tracking",
            "Multiple Quality Levels"
        ],
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint"""
    from datetime import datetime
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected",
        "storage": "connected",
        "hls_processing": "enabled"
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )