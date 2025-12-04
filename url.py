from minio import Minio
from datetime import timedelta

client = Minio(
    "localhost:9000",
    access_key="minioadmin",
    secret_key="minioadmin123",
    secure=False
)

url = client.presigned_get_object(
    "stream-lms-hls",
    "692d63541212f4b402e51075/480p/playlist_480p.m3u8",
    expires=timedelta(hours=1)
)
print(url)
