from flask import Blueprint, render_template, request, current_app
from flask_login import current_user
from app.models import Video, Category, Tag, User, ViewHistory
from app import db
from sqlalchemy import desc, or_
from datetime import datetime, timezone, timedelta
import math
from collections import Counter

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    category_slug = request.args.get('category')
    sort = request.args.get('sort', 'latest')
    query = Video.query.filter_by(status='published', visibility='public')
    if category_slug:
        cat = Category.query.filter_by(slug=category_slug).first()
        if cat:
            query = query.filter_by(category_id=cat.id)
    if sort == 'popular':
        query = query.order_by(desc(Video.views))
    elif sort == 'trending':
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        query = query.filter(Video.published_at >= week_ago).order_by(desc(Video.views))
    else:
        query = query.order_by(desc(Video.published_at))
    videos = query.paginate(page=page, per_page=current_app.config['VIDEOS_PER_PAGE'], error_out=False)
    categories = Category.query.all()
    featured = Video.query.filter_by(status='published', visibility='public') \
                         .order_by(desc(Video.views)).first()
    recommended = []
    if current_user.is_authenticated:
        recommended = get_recommendations(current_user, limit=6)
    return render_template('index.html', videos=videos, categories=categories,
                           featured=featured, recommended=recommended,
                           current_sort=sort, current_category=category_slug)


@main_bp.route('/search')
def search():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'relevance')
    duration = request.args.get('duration')
    category_id = request.args.get('category', type=int)
    videos = None
    users = None
    if q:
        vq = Video.query.filter(
            Video.status == 'published', Video.visibility == 'public',
            or_(Video.title.ilike(f'%{q}%'), Video.description.ilike(f'%{q}%'))
        )
        if category_id:
            vq = vq.filter_by(category_id=category_id)
        if duration == 'short':
            vq = vq.filter(Video.duration < 240)
        elif duration == 'medium':
            vq = vq.filter(Video.duration.between(240, 1200))
        elif duration == 'long':
            vq = vq.filter(Video.duration > 1200)
        if sort == 'views':
            vq = vq.order_by(desc(Video.views))
        elif sort == 'newest':
            vq = vq.order_by(desc(Video.published_at))
        else:
            vq = vq.order_by(desc(Video.views))
        videos = vq.paginate(page=page, per_page=12, error_out=False)
        users = User.query.filter(
            User.is_active == True,
            or_(User.username.ilike(f'%{q}%'), User.display_name.ilike(f'%{q}%'))
        ).limit(5).all()
    categories = Category.query.all()
    return render_template('search.html', videos=videos, users=users, query=q,
                           categories=categories, current_sort=sort,
                           current_duration=duration, current_category=category_id)


@main_bp.route('/trending')
def trending():
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    videos = Video.query.filter(
        Video.status == 'published', Video.visibility == 'public',
        Video.published_at >= week_ago
    ).order_by(desc(Video.views)).limit(24).all()
    return render_template('trending.html', videos=videos)


@main_bp.route('/categories')
def categories():
    return render_template('categories.html', categories=Category.query.all())


@main_bp.route('/tag/<slug>')
def tag(slug):
    tag_obj = Tag.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    videos = tag_obj.videos.filter_by(status='published', visibility='public') \
                           .order_by(desc(Video.published_at)) \
                           .paginate(page=page, per_page=12, error_out=False)
    return render_template('tag.html', tag=tag_obj, videos=videos)


@main_bp.route('/roadmap')
def roadmap():
    return render_template('static/roadmap.html')


@main_bp.route('/about')
def about():
    return render_template('static/about.html')


@main_bp.route('/help')
def help_page():
    return render_template('static/help.html')


@main_bp.route('/api-docs')
def api_docs():
    return render_template('static/api_docs.html')


def get_recommendations(user, limit=12):
    now = datetime.now(timezone.utc)
    liked = user.likes.filter_by(is_like=True).limit(50).all()
    watched = ViewHistory.query.filter_by(user_id=user.id) \
                               .order_by(desc(ViewHistory.created_at)).limit(100).all()
    liked_ids = {l.video_id for l in liked}
    watched_ids = {w.video_id for w in watched}
    cat_counter = Counter()
    for l in liked:
        v = db.session.get(Video, l.video_id)
        if v and v.category_id:
            cat_counter[v.category_id] += 3
    for w in watched:
        v = db.session.get(Video, w.video_id)
        if v and v.category_id:
            cat_counter[v.category_id] += 2
    tag_counter = Counter()
    for vid_id in list(liked_ids)[:30]:
        v = db.session.get(Video, vid_id)
        if v:
            for t in v.tags:
                tag_counter[t.id] += 1
    sub_ids = {u.id for u in user.subscribed_to.all()}
    candidates = Video.query.filter_by(status='published', visibility='public') \
                            .filter(Video.user_id != user.id).all()
    scored = []
    for v in candidates:
        tr = v.like_count() + v.dislike_count()
        lr = v.like_count() / tr if tr > 0 else 0.5
        sat = (lr ** 2) * math.log(v.views + 2)
        if v.published_at:
            pub = v.published_at.replace(tzinfo=timezone.utc) \
                  if v.published_at.tzinfo is None else v.published_at
            age = max((now - pub).total_seconds() / 86400, 0)
        else:
            age = 365
        fresh = math.exp(-age / 30)
        pers = 1.0
        if v.category_id and v.category_id in cat_counter:
            pers += min(cat_counter[v.category_id] / 5.0, 3.0)
        overlap = sum(tag_counter.get(t.id, 0) for t in v.tags)
        pers += min(overlap * 0.3, 1.5)
        if v.user_id in sub_ids:
            pers += 2.5
        penalty = 10.0 if v.id in watched_ids else 5.0 if v.id in liked_ids else 1.0
        scored.append(((sat * fresh * pers) / penalty, v))
    scored.sort(key=lambda x: x[0], reverse=True)
    result = [v for _, v in scored[:limit]]
    if not result:
        result = Video.query.filter_by(status='published', visibility='public') \
                            .order_by(desc(Video.views)).limit(limit).all()
    return result
