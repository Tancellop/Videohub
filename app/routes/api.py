from flask import Blueprint, jsonify, request, current_app
from flask_login import current_user
from app.models import Video, User, Category, Tag, Comment, Like
from app import db, limiter, csrf
from sqlalchemy import desc, or_
import jwt
from datetime import datetime, timezone, timedelta
from functools import wraps

api_bp = Blueprint('api', __name__)
csrf.exempt(api_bp)


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        try:
            data = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            user = db.session.get(User, data['user_id'])
            if not user or user.is_banned:
                return jsonify({'error': 'Invalid token'}), 401
            request.api_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated


def video_to_dict(video, full=False):
    data = {
        'id': video.id,
        'title': video.title,
        'slug': video.slug,
        'thumbnail': f'/videos/thumbnail/{video.thumbnail}' if video.thumbnail else None,
        'duration': video.duration,
        'duration_str': video.duration_str(),
        'views': video.views,
        'likes': video.like_count(),
        'created_at': video.created_at.isoformat(),
        'author': {
            'username': video.author.username,
            'display_name': video.author.display_name,
            'avatar': video.author.avatar
        },
        'category': {
            'id': video.category.id,
            'name': video.category.name,
            'slug': video.category.slug
        } if video.category else None,
        'tags': [{'id': t.id, 'name': t.name, 'slug': t.slug} for t in video.tags]
    }
    
    if full:
        data['description'] = video.description
        data['dislikes'] = video.dislike_count()
        data['comment_count'] = video.comment_count()
        data['resolution'] = video.resolution
        data['file_size'] = video.file_size
    
    return data


def user_to_dict(user):
    return {
        'id': user.id,
        'username': user.username,
        'display_name': user.display_name,
        'bio': user.bio,
        'avatar': user.avatar,
        'subscriber_count': user.subscriber_count(),
        'video_count': user.video_count(),
        'total_views': user.total_views(),
        'created_at': user.created_at.isoformat()
    }


# --- AUTH ---

@api_bp.route('/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    login_field = data.get('login', '')
    password = data.get('password', '')
    
    user = None
    if '@' in login_field:
        user = User.query.filter_by(email=login_field.lower()).first()
    else:
        user = User.query.filter_by(username=login_field).first()
    
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid credentials'}), 401
    
    if not user.is_verified:
        return jsonify({'error': 'Email not verified'}), 403
    
    if user.is_banned:
        return jsonify({'error': 'Account banned'}), 403
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
    }, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    
    return jsonify({
        'token': token,
        'user': user_to_dict(user)
    })


@api_bp.route('/auth/me')
@token_required
def api_me():
    return jsonify(user_to_dict(request.api_user))


# --- VIDEOS ---

@api_bp.route('/videos')
@limiter.limit("60 per minute")
def api_videos():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 12, type=int), 50)
    category = request.args.get('category')
    sort = request.args.get('sort', 'latest')
    q = request.args.get('q', '')
    
    query = Video.query.filter_by(status='published', visibility='public')
    
    if category:
        cat = Category.query.filter_by(slug=category).first()
        if cat:
            query = query.filter_by(category_id=cat.id)
    
    if q:
        query = query.filter(or_(
            Video.title.ilike(f'%{q}%'),
            Video.description.ilike(f'%{q}%')
        ))
    
    if sort == 'popular':
        query = query.order_by(desc(Video.views))
    elif sort == 'trending':
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        query = query.filter(Video.published_at >= week_ago).order_by(desc(Video.views))
    else:
        query = query.order_by(desc(Video.published_at))
    
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'videos': [video_to_dict(v) for v in paginated.items],
        'total': paginated.total,
        'pages': paginated.pages,
        'current_page': page,
        'per_page': per_page
    })


@api_bp.route('/videos/<slug>')
def api_video(slug):
    video = Video.query.filter_by(slug=slug, status='published', visibility='public').first_or_404()
    return jsonify(video_to_dict(video, full=True))


@api_bp.route('/videos/<int:video_id>/comments')
def api_comments(video_id):
    video = Video.query.get_or_404(video_id)
    page = request.args.get('page', 1, type=int)
    
    comments = Comment.query.filter_by(
        video_id=video_id, parent_id=None, is_hidden=False
    ).order_by(desc(Comment.created_at)).paginate(page=page, per_page=20, error_out=False)
    
    def comment_to_dict(c):
        return {
            'id': c.id,
            'content': c.content,
            'created_at': c.created_at.isoformat(),
            'author': {
                'username': c.author.username,
                'display_name': c.author.display_name,
                'avatar': c.author.avatar
            },
            'replies_count': c.replies.count()
        }
    
    return jsonify({
        'comments': [comment_to_dict(c) for c in comments.items],
        'total': comments.total,
        'pages': comments.pages,
        'current_page': page
    })


@api_bp.route('/videos/<int:video_id>/like', methods=['POST'])
@token_required
def api_like(video_id):
    video = Video.query.get_or_404(video_id)
    is_like = request.get_json().get('is_like', True)
    user = request.api_user
    
    existing = Like.query.filter_by(user_id=user.id, video_id=video_id).first()
    
    if existing:
        if existing.is_like == is_like:
            db.session.delete(existing)
        else:
            existing.is_like = is_like
    else:
        like = Like(user_id=user.id, video_id=video_id, is_like=is_like)
        db.session.add(like)
    
    db.session.commit()
    return jsonify({'likes': video.like_count(), 'dislikes': video.dislike_count()})


# --- USERS ---

@api_bp.route('/users/<username>')
def api_user(username):
    user = User.query.filter_by(username=username, is_active=True).first_or_404()
    return jsonify(user_to_dict(user))


@api_bp.route('/users/<username>/videos')
def api_user_videos(username):
    user = User.query.filter_by(username=username, is_active=True).first_or_404()
    page = request.args.get('page', 1, type=int)
    
    videos = Video.query.filter_by(
        user_id=user.id, status='published', visibility='public'
    ).order_by(desc(Video.published_at)).paginate(page=page, per_page=12, error_out=False)
    
    return jsonify({
        'videos': [video_to_dict(v) for v in videos.items],
        'total': videos.total,
        'pages': videos.pages
    })


# --- CATEGORIES ---

@api_bp.route('/categories')
def api_categories():
    cats = Category.query.all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'slug': c.slug,
        'icon': c.icon,
        'video_count': c.video_count()
    } for c in cats])


# --- SEARCH ---

@api_bp.route('/search')
@limiter.limit("30 per minute")
def api_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'videos': [], 'users': []})
    
    videos = Video.query.filter(
        Video.status == 'published',
        Video.visibility == 'public',
        or_(Video.title.ilike(f'%{q}%'), Video.description.ilike(f'%{q}%'))
    ).order_by(desc(Video.views)).limit(10).all()
    
    users = User.query.filter(
        User.is_active == True,
        or_(User.username.ilike(f'%{q}%'), User.display_name.ilike(f'%{q}%'))
    ).limit(5).all()
    
    return jsonify({
        'videos': [video_to_dict(v) for v in videos],
        'users': [user_to_dict(u) for u in users]
    })


# --- ERROR HANDLERS ---

@api_bp.errorhandler(404)
def api_404(e):
    return jsonify({'error': 'Not found'}), 404


@api_bp.errorhandler(403)
def api_403(e):
    return jsonify({'error': 'Forbidden'}), 403


@api_bp.errorhandler(429)
def api_429(e):
    return jsonify({'error': 'Rate limit exceeded'}), 429
