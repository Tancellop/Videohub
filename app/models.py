from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login_manager
import secrets, json, re

video_tags = db.Table('video_tags',
    db.Column('video_id', db.Integer, db.ForeignKey('videos.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True)
)
subscriptions = db.Table('subscriptions',
    db.Column('subscriber_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('channel_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('created_at', db.DateTime, default=lambda: datetime.now(timezone.utc))
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256))
    display_name = db.Column(db.String(100))
    bio = db.Column(db.Text, default='')
    avatar = db.Column(db.String(255), default='default_avatar.png')
    banner = db.Column(db.String(255))
    role = db.Column(db.String(20), default='user')
    is_verified = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    is_banned = db.Column(db.Boolean, default=False)
    ban_reason = db.Column(db.String(255))
    verification_token = db.Column(db.String(100))
    reset_token = db.Column(db.String(100))
    reset_token_expires = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    preferences = db.Column(db.Text, default='{}')
    videos = db.relationship('Video', backref='author', lazy='dynamic', foreign_keys='Video.user_id')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    likes = db.relationship('Like', backref='user', lazy='dynamic')
    playlists = db.relationship('Playlist', backref='owner', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic', foreign_keys='Notification.user_id')
    subscribed_to = db.relationship(
        'User', secondary=subscriptions,
        primaryjoin=(subscriptions.c.subscriber_id == id),
        secondaryjoin=(subscriptions.c.channel_id == id),
        backref=db.backref('subscribers', lazy='dynamic'), lazy='dynamic'
    )
    def set_password(self, p): self.password_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.password_hash, p)
    def generate_verification_token(self):
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token
    def generate_reset_token(self):
        from datetime import timedelta
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        return self.reset_token
    def is_subscribed_to(self, user):
        return self.subscribed_to.filter(subscriptions.c.channel_id == user.id).count() > 0
    def subscriber_count(self): return self.subscribers.count()
    def video_count(self): return self.videos.filter_by(status='published').count()
    def total_views(self):
        r = db.session.query(db.func.sum(Video.views)).filter(Video.user_id==self.id, Video.status=='published').scalar()
        return r or 0
    @property
    def is_admin(self): return self.role == 'admin'
    @property
    def is_moderator(self): return self.role in ['admin', 'moderator']


@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    icon = db.Column(db.String(10), default='📹')
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    videos = db.relationship('Video', backref='category', lazy='dynamic')
    def video_count(self): return self.videos.filter_by(status='published').count()


class Tag(db.Model):
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Video(db.Model):
    __tablename__ = 'videos'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    slug = db.Column(db.String(250), unique=True, index=True)
    filename = db.Column(db.String(255), nullable=False)
    thumbnail = db.Column(db.String(255))
    duration = db.Column(db.Integer, default=0)
    file_size = db.Column(db.BigInteger, default=0)
    resolution = db.Column(db.String(20))
    format = db.Column(db.String(20))
    status = db.Column(db.String(20), default='processing')
    visibility = db.Column(db.String(20), default='public')
    views = db.Column(db.Integer, default=0)
    has_360p = db.Column(db.Boolean, default=False)
    has_720p = db.Column(db.Boolean, default=False)
    has_1080p = db.Column(db.Boolean, default=False)
    is_short = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    published_at = db.Column(db.DateTime)
    tags = db.relationship('Tag', secondary=video_tags, backref=db.backref('videos', lazy='dynamic'))
    comments = db.relationship('Comment', backref='video', lazy='dynamic', cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='video', lazy='dynamic', cascade='all, delete-orphan')
    def like_count(self): return self.likes.filter_by(is_like=True).count()
    def dislike_count(self): return self.likes.filter_by(is_like=False).count()
    def comment_count(self): return self.comments.filter_by(parent_id=None, is_hidden=False).count()
    def is_liked_by(self, user):
        if not user or not user.is_authenticated: return None
        like = self.likes.filter_by(user_id=user.id).first()
        return like.is_like if like else None
    def get_tags_str(self): return ', '.join([t.name for t in self.tags])
    def duration_str(self):
        if not self.duration: return '0:00'
        h = self.duration // 3600; m = (self.duration % 3600) // 60; s = self.duration % 60
        return f'{h}:{m:02d}:{s:02d}' if h > 0 else f'{m}:{s:02d}'
    def file_size_str(self):
        sz = self.file_size or 0
        if sz < 1024: return f'{sz} B'
        if sz < 1024**2: return f'{sz/1024:.1f} KB'
        if sz < 1024**3: return f'{sz/1024**2:.1f} MB'
        return f'{sz/1024**3:.2f} GB'


class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comments.id'))
    is_hidden = db.Column(db.Boolean, default=False)
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]),
                              lazy='dynamic', cascade='all, delete-orphan')


class Like(db.Model):
    __tablename__ = 'likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    is_like = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('user_id', 'video_id'),)


class Playlist(db.Model):
    __tablename__ = 'playlists'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    visibility = db.Column(db.String(20), default='public')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ViewHistory(db.Model):
    __tablename__ = 'view_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    ip_address = db.Column(db.String(45))
    session_id = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    video = db.relationship('Video')


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    type = db.Column(db.String(50))
    message = db.Column(db.String(255))
    url = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    actor = db.relationship('User', foreign_keys=[actor_id])


class Report(db.Model):
    __tablename__ = 'reports'
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'))
    reason = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reporter = db.relationship('User')
    video = db.relationship('Video')


class Stream(db.Model):
    __tablename__ = 'streams'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    stream_key = db.Column(db.String(64), unique=True, nullable=False)
    status = db.Column(db.String(20), default='offline')
    viewer_count = db.Column(db.Integer, default=0)
    peak_viewers = db.Column(db.Integer, default=0)
    thumbnail = db.Column(db.String(255))
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    saved_video_id = db.Column(db.Integer, db.ForeignKey('videos.id'))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    author = db.relationship('User', backref='streams')
    category = db.relationship('Category')
    messages = db.relationship('StreamMessage', backref='stream', lazy='dynamic', cascade='all, delete-orphan')
    def generate_key(self):
        self.stream_key = secrets.token_hex(24)
        return self.stream_key
    def is_live(self): return self.status == 'live'


class StreamMessage(db.Model):
    __tablename__ = 'stream_messages'
    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey('streams.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    is_hidden = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    author = db.relationship('User')


class Channel(db.Model):
    __tablename__ = 'channels'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(110), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, default='')
    avatar = db.Column(db.String(255))
    banner = db.Column(db.String(255))
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    owner = db.relationship('User', backref='owned_channels')
    members = db.relationship('ChannelMember', backref='channel', cascade='all, delete-orphan')
    videos = db.relationship('ChannelVideo', backref='channel', cascade='all, delete-orphan')
    def subscriber_count(self): return ChannelSubscription.query.filter_by(channel_id=self.id).count()
    def video_count(self): return ChannelVideo.query.filter_by(channel_id=self.id).count()
    def get_member_role(self, user):
        if not user or not user.is_authenticated: return None
        m = ChannelMember.query.filter_by(channel_id=self.id, user_id=user.id).first()
        return m.role if m else None
    def is_member(self, user): return self.get_member_role(user) is not None


class ChannelMember(db.Model):
    __tablename__ = 'channel_members'
    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channels.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), default='editor')
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('channel_id', 'user_id'),)


class ChannelVideo(db.Model):
    __tablename__ = 'channel_videos'
    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channels.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    posted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    posted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    video = db.relationship('Video')
    poster = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('channel_id', 'video_id'),)


class ChannelSubscription(db.Model):
    __tablename__ = 'channel_subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channels.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('channel_id', 'user_id'),)


class PlaylistItem(db.Model):
    __tablename__ = 'playlist_items'
    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlists.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    position = db.Column(db.Integer, default=0)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    video = db.relationship('Video')


class CommentLike(db.Model):
    __tablename__ = 'comment_likes'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user       = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('user_id', 'comment_id'),)
