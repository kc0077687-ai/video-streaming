from pymongo import MongoClient
from config import settings

mongo = MongoClient(settings.MONGO_URL)
celery_db = mongo[settings.DATABASE_NAME]
