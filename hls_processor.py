"""
HLS Video Processing with FFmpeg
Converts uploaded videos to adaptive bitrate HLS streams
"""
import os
import subprocess
import shutil
from typing import List, Dict
from pathlib import Path
import logging
import minio
from config import settings, VIDEO_QUALITIES

logger = logging.getLogger(__name__)

minio_client = minio.Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE
)

def upload_hls_variant(local_dir: str, video_id: str, quality: str):
    for file in os.listdir(local_dir):
        full_path = os.path.join(local_dir, file)
        object_name = f"{video_id}/{quality}/{file}"
        content_type = "application/vnd.apple.mpegurl" if file.endswith(".m3u8") else "video/MP2T"
        minio_client.fput_object(settings.HLS_BUCKET, object_name, full_path, content_type=content_type)

class HLSProcessor:
    """Process videos for HLS streaming"""
    
    def __init__(self, temp_dir: str = None):
        self.temp_dir = temp_dir or settings.TEMP_UPLOAD_DIR
        os.makedirs(self.temp_dir, exist_ok=True)
    
    def process_video_to_hls(
        self, 
        input_video_path: str, 
        output_dir: str, 
        video_id: str,
        qualities: List[str] = None
    ) -> Dict[str, str]:

        if qualities is None:
            qualities = settings.HLS_QUALITIES

        os.makedirs(output_dir, exist_ok=True)

        # Get video info
        video_info = self._get_video_info(input_video_path)
        source_height = video_info["height"]

        # Filter qualities
        available_qualities = self._filter_qualities(source_height, qualities)

        variant_playlists = []   # <-- FIX: define here

        # Generate HLS files for each quality
        for quality in available_qualities:
            q_dir = os.path.join(output_dir, quality)
            os.makedirs(q_dir, exist_ok=True)

            playlist_path = self._generate_hls_stream(
                input_video_path,
                q_dir,
                quality,
                video_id
            )

            if playlist_path:
                # Upload to MinIO
                upload_hls_variant(q_dir, video_id, quality)

                variant_playlists.append({
                    "quality": quality,
                    "resolution": VIDEO_QUALITIES[quality],
                    "playlist_path": playlist_path
                })

        if not variant_playlists:
            return {"success": False, "error": "No variants generated"}

        # Generate master playlist
        try:
            master_playlist_path = self._generate_master_playlist(
                output_dir,
                variant_playlists,
                video_id
            )
        except Exception as e:
            logger.error(f"Failed to generate master playlist: {e}")
            return {
                "success": False,
                "error": f"Failed to generate master playlist: {e}"
            }

        return {
            "success": True,
            "master_playlist": master_playlist_path,
            "variants": variant_playlists,
            "output_dir": output_dir
        }

       
    def _get_video_info(self, video_path: str) -> Dict:
        """Get video metadata using ffprobe"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,duration',
                '-of', 'json',
                video_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            import json
            data = json.loads(result.stdout)
            stream = data['streams'][0] if data.get('streams') else {}
            
            return {
                'width': int(stream.get('width', 0)),
                'height': int(stream.get('height', 0)),
                'duration': float(stream.get('duration', 0))
            }
        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
            return {'width': 0, 'height': 0, 'duration': 0}
    
    def _filter_qualities(self, source_height: int, requested_qualities: List[str]) -> List[str]:
        """Filter qualities that are appropriate for the source video"""
        available = []
        for quality in requested_qualities:
            quality_height = VIDEO_QUALITIES[quality]['height']
            if quality_height <= source_height:
                available.append(quality)
        
        # Always include at least one quality
        if not available and requested_qualities:
            available.append(requested_qualities[0])
        
        return available
    
    def _generate_hls_stream(
        self, 
        input_path: str, 
        output_dir: str, 
        quality: str,
        video_id: str
    ) -> str:
        """Generate HLS stream for a specific quality"""
        try:
            quality_config = VIDEO_QUALITIES[quality]
            playlist_name = f"playlist_{quality}.m3u8"
            playlist_path = os.path.join(output_dir, playlist_name)
            segment_pattern = os.path.join(output_dir, f"segment_{quality}_%03d.ts")
            
            # FFmpeg command for HLS conversion
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-vf', f"scale={quality_config['width']}:{quality_config['height']}",
                '-c:v', 'libx264',
                '-b:v', quality_config['bitrate'],
                '-c:a', 'aac',
                '-b:a', '128k',
                '-f', 'hls',
                '-hls_time', str(settings.HLS_SEGMENT_DURATION),
                '-hls_playlist_type', 'vod',
                '-hls_segment_filename', segment_pattern,
                '-hls_list_size', '0',
                playlist_path
            ]
            
            logger.info(f"Generating {quality} stream for {video_id}")
            
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            
            logger.info(f"Successfully generated {quality} stream")
            return playlist_path
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error for {quality}: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"Failed to generate {quality} stream: {e}")
            return None
    
    def _generate_master_playlist(
        self, 
        output_dir: str, 
        variants: List[Dict],
        video_id: str
    ) -> str:
        """Generate master playlist that references all quality variants"""
        master_playlist_path = os.path.join(output_dir, "master.m3u8")
        
        with open(master_playlist_path, 'w') as f:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n\n")
            
            for variant in variants:
                quality = variant['quality']
                resolution = variant['resolution']
                bandwidth = int(resolution['bitrate'].replace('k', '000'))
                
                f.write(f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},"
                       f"RESOLUTION={resolution['width']}x{resolution['height']}\n")
                playlist_url = f"{settings.HLS_BASE_URL}/{video_id}/{quality}/playlist_{quality}.m3u8"
                f.write(f"{playlist_url}\n\n")

        
        logger.info(f"Generated master playlist for {video_id}")
        return master_playlist_path
    
    def cleanup_temp_files(self, video_id: str):
        """Clean up temporary files after processing"""
        temp_path = os.path.join(self.temp_dir, video_id)
        if os.path.exists(temp_path):
            shutil.rmtree(temp_path)
            logger.info(f"Cleaned up temp files for {video_id}")

# Global processor instance
hls_processor = HLSProcessor()