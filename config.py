import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'videohub-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        f'sqlite:///{os.path.join(BASE_DIR, "videohub.db")}'
    # Neon and some providers return 'postgres://' which SQLAlchemy rejects
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER                  = os.path.join(BASE_DIR, 'app', 'static', 'uploads')
    VIDEO_FOLDER                   = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'videos')
    THUMBNAIL_FOLDER               = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'thumbnails')
    AVATAR_FOLDER                  = os.path.join(BASE_DIR, 'app', 'static', 'uploads', 'avatars')
    MAX_CONTENT_LENGTH             = 2 * 1024 * 1024 * 1024
    ALLOWED_VIDEO_EXTENSIONS       = {'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', 'wmv', 'm4v'}
    ALLOWED_IMAGE_EXTENSIONS       = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    MAIL_SERVER                    = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT                      = 587
    MAIL_USE_TLS                   = True
    MAIL_USERNAME                  = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD                  = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER            = 'noreply@videohub.com'
    CLOUDINARY_CLOUD_NAME          = os.environ.get('CLOUDINARY_CLOUD_NAME')
    CLOUDINARY_API_KEY             = os.environ.get('CLOUDINARY_API_KEY')
    CLOUDINARY_API_SECRET          = os.environ.get('CLOUDINARY_API_SECRET')
    JWT_SECRET_KEY                 = os.environ.get('JWT_SECRET_KEY') or 'jwt-secret-change-me'
    JWT_ACCESS_TOKEN_EXPIRES       = timedelta(hours=24)
    VIDEOS_PER_PAGE                = 12
    FFMPEG_PATH                    = 'ffmpeg'
    FFPROBE_PATH                   = 'ffprobe'
    THUMBNAIL_SIZE                 = (640, 360)
    WTF_CSRF_ENABLED               = True
    WTF_CSRF_TIME_LIMIT            = None                                                              # токен не истекает пока сессия активна
    SESSION_COOKIE_HTTPONLY        = True
    SESSION_COOKIE_SAMESITE        = 'Lax'
    RATELIMIT_STORAGE_URL          = 'memory://'

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
