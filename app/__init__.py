import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from config import config

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Войдите для доступа к этой странице.'
login_manager.login_message_category = 'info'


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    for folder in [
        app.config['VIDEO_FOLDER'],
        app.config['THUMBNAIL_FOLDER'],
        app.config.get('AVATAR_FOLDER', ''),
        os.path.join(app.config['UPLOAD_FOLDER'], 'banners'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'channel_avatars'),
        os.path.join(app.config['UPLOAD_FOLDER'], 'channel_banners'),
    ]:
        if folder:
            os.makedirs(folder, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.videos import videos_bp
    from app.routes.users import users_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    from app.routes.streams import streams_bp
    from app.routes.shorts import shorts_bp
    from app.routes.channels import channels_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(videos_bp, url_prefix='/videos')
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api/v1')
    app.register_blueprint(streams_bp, url_prefix='/live')
    app.register_blueprint(shorts_bp, url_prefix='/shorts')
    app.register_blueprint(channels_bp, url_prefix='/channels')
    from app.routes.errors import register_errors
    register_errors(app)
    with app.app_context():
        db.create_all()
        _migrate_columns()
        _create_default_data()
    from app.utils.filters import register_filters
    register_filters(app)
    from app.utils.context_processors import register_context_processors
    register_context_processors(app)
    return app


def _migrate_columns():
    from sqlalchemy import text
    cols = [
        ('videos', 'is_short', 'BOOLEAN', 'FALSE'),
        ('streams', 'saved_video_id', 'INTEGER', 'NULL'),
        ('view_history', 'session_id', 'VARCHAR(128)', 'NULL'),
    ]
    with db.engine.connect() as conn:
        for table, column, ctype, default in cols:
            try:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ctype} DEFAULT {default}'))
                conn.commit()
            except Exception:
                pass
        # Verify all existing users — email verification is disabled
        try:
            conn.execute(text('UPDATE users SET is_verified = 1 WHERE is_verified = 0'))
            conn.commit()
        except Exception:
            pass


def _create_default_data():
    from app.models import Category, User
    cats = [
        ('Музыка','music','🎵'),('Игры','gaming','🎮'),('Образование','education','📚'),
        ('Технологии','tech','💻'),('Спорт','sports','⚽'),('Развлечения','entertainment','🎭'),
        ('Путешествия','travel','✈️'),('Кулинария','cooking','🍳'),('Наука','science','🔬'),('Новости','news','📰'),
    ]
    for name, slug, icon in cats:
        if not Category.query.filter_by(slug=slug).first():
            db.session.add(Category(name=name, slug=slug, icon=icon))
    if not User.query.filter_by(role='admin').first():
        admin = User(username='admin', email='admin@videohub.com',
                     role='admin', is_verified=True, display_name='Administrator')
        admin.set_password('Admin123!')
        db.session.add(admin)
    db.session.commit()
