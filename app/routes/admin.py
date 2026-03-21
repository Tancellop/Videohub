import os
import re
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, abort, current_app)
from flask_login import login_required, current_user
from app import db
from app.models import (User, Video, Comment, Category, Tag,
                        Report, Notification, Like, ViewHistory)
from sqlalchemy import desc, func
from datetime import datetime, timezone, timedelta
from functools import wraps

admin_bp = Blueprint('admin', __name__)


# ── Decorators ────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def moderator_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_moderator:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route('/')
@login_required
@moderator_required
def dashboard():
    total_users    = User.query.count()
    total_videos   = Video.query.filter_by(is_short=False).count()
    total_shorts   = Video.query.filter_by(is_short=True).count()
    total_views    = db.session.query(func.sum(Video.views)).scalar() or 0
    total_comments = Comment.query.count()
    total_likes    = Like.query.count()
    banned_users   = User.query.filter_by(is_banned=True).count()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    new_users_today  = User.query.filter(User.created_at >= today_start).count()
    new_videos_today = Video.query.filter(Video.created_at >= today_start).count()
    pending_reports  = Report.query.filter_by(status='pending').count()

    recent_users  = User.query.order_by(desc(User.created_at)).limit(5).all()
    recent_videos = Video.query.order_by(desc(Video.created_at)).limit(5).all()

    chart_data = []
    for i in range(6, -1, -1):
        date  = datetime.now(timezone.utc) - timedelta(days=i)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        chart_data.append({
            'date':   date.strftime('%d.%m'),
            'users':  User.query.filter(User.created_at.between(start, end)).count(),
            'videos': Video.query.filter(Video.created_at.between(start, end)).count(),
        })

    return render_template('admin/dashboard.html',
                           total_users=total_users,
                           total_videos=total_videos,
                           total_shorts=total_shorts,
                           total_views=total_views,
                           total_comments=total_comments,
                           total_likes=total_likes,
                           banned_users=banned_users,
                           new_users_today=new_users_today,
                           new_videos_today=new_videos_today,
                           pending_reports=pending_reports,
                           recent_users=recent_users,
                           recent_videos=recent_videos,
                           chart_data=chart_data)


# ── Users ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@login_required
@moderator_required
def users():
    page        = request.args.get('page', 1, type=int)
    search      = request.args.get('search', '')
    role_filter = request.args.get('role', '')
    ban_filter  = request.args.get('banned', '')

    query = User.query
    if search:
        query = query.filter(
            db.or_(User.username.ilike(f'%{search}%'),
                   User.email.ilike(f'%{search}%'),
                   User.display_name.ilike(f'%{search}%'))
        )
    if role_filter:
        query = query.filter_by(role=role_filter)
    if ban_filter == '1':
        query = query.filter_by(is_banned=True)
    elif ban_filter == '0':
        query = query.filter_by(is_banned=False)

    users = query.order_by(desc(User.created_at)).paginate(
        page=page, per_page=20, error_out=False)
    return render_template('admin/users.html', users=users,
                           search=search, role_filter=role_filter, ban_filter=ban_filter)


@admin_bp.route('/users/<int:user_id>/action', methods=['POST'])
@login_required
@moderator_required
def user_action(user_id):
    user   = User.query.get_or_404(user_id)
    body   = request.get_json(silent=True) or {}
    action = body.get('action')

    # Protect admins from mods
    if user.is_admin and not current_user.is_admin:
        return jsonify({'error': 'Недостаточно прав'}), 403
    # Protect self
    if user.id == current_user.id and action in ('ban', 'delete', 'set_role'):
        return jsonify({'error': 'Нельзя применить это действие к себе'}), 403

    if action == 'ban':
        user.is_banned  = True
        user.ban_reason = body.get('reason', 'Нарушение правил')
        msg = f'Пользователь {user.username} заблокирован'

    elif action == 'unban':
        user.is_banned  = False
        user.ban_reason = None
        msg = f'Пользователь {user.username} разблокирован'

    elif action == 'set_role' and current_user.is_admin:
        role = body.get('role', 'user')
        if role not in ('user', 'moderator', 'admin'):
            return jsonify({'error': 'Неверная роль'}), 400
        user.role = role
        msg = f'Роль {user.username} → {role}'

    elif action == 'edit' and current_user.is_admin:
        # Edit user details
        new_name  = body.get('display_name', '').strip()
        new_email = body.get('email', '').strip().lower()
        if new_name:
            user.display_name = new_name[:100]
        if new_email and new_email != user.email:
            if User.query.filter(User.email == new_email, User.id != user.id).first():
                return jsonify({'error': 'Email уже занят'}), 400
            user.email = new_email
        msg = f'Данные {user.username} обновлены'

    elif action == 'delete' and current_user.is_admin:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Пользователь удалён'})

    else:
        return jsonify({'error': 'Неизвестное действие'}), 400

    db.session.commit()
    return jsonify({'success': True, 'message': msg})


# ── Videos ────────────────────────────────────────────────────────────────────

@admin_bp.route('/videos')
@login_required
@moderator_required
def videos():
    page          = request.args.get('page', 1, type=int)
    search        = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    type_filter   = request.args.get('type', '')   # 'short' | 'video' | ''

    query = Video.query
    if search:
        query = query.filter(Video.title.ilike(f'%{search}%'))
    if status_filter:
        query = query.filter_by(status=status_filter)
    if type_filter == 'short':
        query = query.filter_by(is_short=True)
    elif type_filter == 'video':
        query = query.filter_by(is_short=False)

    videos = query.order_by(desc(Video.created_at)).paginate(
        page=page, per_page=20, error_out=False)
    return render_template('admin/videos.html', videos=videos,
                           search=search, status_filter=status_filter,
                           type_filter=type_filter)


@admin_bp.route('/videos/<int:video_id>/action', methods=['POST'])
@login_required
@moderator_required
def video_action(video_id):
    video  = Video.query.get_or_404(video_id)
    body   = request.get_json(silent=True) or {}
    action = body.get('action')

    if action == 'publish':
        video.status = 'published'
        if not video.published_at:
            video.published_at = datetime.now(timezone.utc)

    elif action == 'unpublish':
        video.status = 'draft'

    elif action == 'edit':
        # Edit title, description, views, visibility, category
        if body.get('title'):
            video.title = body['title'].strip()[:200]
        if body.get('description') is not None:
            video.description = body['description']
        if body.get('views') is not None:
            try:
                v = int(body['views'])
                if v >= 0:
                    video.views = v
            except (ValueError, TypeError):
                pass
        if body.get('visibility') in ('public', 'private', 'unlisted'):
            video.visibility = body['visibility']
        if body.get('category_id') is not None:
            video.category_id = body['category_id'] or None

    elif action == 'delete':
        try:
            fp = os.path.join(current_app.config['VIDEO_FOLDER'], video.filename)
            if os.path.exists(fp):
                os.remove(fp)
            if video.thumbnail:
                tp = os.path.join(current_app.config['THUMBNAIL_FOLDER'], video.thumbnail)
                if os.path.exists(tp):
                    os.remove(tp)
        except Exception as e:
            current_app.logger.error(f'File delete error: {e}')
        db.session.delete(video)
        db.session.commit()
        return jsonify({'success': True})

    else:
        return jsonify({'error': 'Неизвестное действие'}), 400

    db.session.commit()
    return jsonify({'success': True})


# ── Categories ────────────────────────────────────────────────────────────────

@admin_bp.route('/categories', methods=['GET', 'POST'])
@login_required
@admin_required
def categories():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            name        = request.form.get('name', '').strip()
            icon        = request.form.get('icon', '📹').strip() or '📹'
            description = request.form.get('description', '')
            slug        = re.sub(r'[^\w\s-]', '', name.lower())
            slug        = re.sub(r'[-\s]+', '-', slug).strip('-')

            if name and not Category.query.filter_by(slug=slug).first():
                db.session.add(Category(name=name, slug=slug,
                                        icon=icon, description=description))
                db.session.commit()
                flash(f'Категория «{name}» создана.', 'success')
            else:
                flash('Название уже занято или не указано.', 'error')

        elif action == 'delete':
            cat = db.session.get(Category, request.form.get('category_id', type=int))
            if cat:
                Video.query.filter_by(category_id=cat.id).update({'category_id': None})
                db.session.delete(cat)
                db.session.commit()
                flash('Категория удалена.', 'info')

        return redirect(url_for('admin.categories'))

    return render_template('admin/categories.html',
                           categories=Category.query.all())


# ── Reports ───────────────────────────────────────────────────────────────────

@admin_bp.route('/reports')
@login_required
@moderator_required
def reports():
    page   = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'pending')
    reports = (Report.query.filter_by(status=status)
               .order_by(desc(Report.created_at))
               .paginate(page=page, per_page=20, error_out=False))
    return render_template('admin/reports.html',
                           reports=reports, current_status=status)


@admin_bp.route('/reports/<int:report_id>/action', methods=['POST'])
@login_required
@moderator_required
def report_action(report_id):
    report = Report.query.get_or_404(report_id)
    body   = request.get_json(silent=True) or {}
    action = body.get('action')

    if action == 'dismiss':
        report.status = 'dismissed'
    elif action == 'review':
        report.status = 'reviewed'
    else:
        return jsonify({'error': 'Неизвестное действие'}), 400

    db.session.commit()
    return jsonify({'success': True})


# ── Stats API ─────────────────────────────────────────────────────────────────

@admin_bp.route('/stats/api')
@login_required
@moderator_required
def stats_api():
    days = min(request.args.get('days', 7, type=int), 90)
    data = []
    for i in range(days - 1, -1, -1):
        date  = datetime.now(timezone.utc) - timedelta(days=i)
        start = date.replace(hour=0,  minute=0,  second=0,  microsecond=0)
        end   = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        data.append({
            'date':   date.strftime('%d.%m'),
            'users':  User.query.filter(User.created_at.between(start, end)).count(),
            'videos': Video.query.filter(Video.created_at.between(start, end)).count(),
        })
    return jsonify(data)


# ── Comments management ───────────────────────────────────────────────────────

@admin_bp.route('/comments')
@login_required
@moderator_required
def comments():
    page   = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    query  = Comment.query
    if search:
        query = query.filter(Comment.content.ilike(f'%{search}%'))
    comments = query.order_by(desc(Comment.created_at)).paginate(
        page=page, per_page=30, error_out=False)
    return render_template('admin/comments.html',
                           comments=comments, search=search)


@admin_bp.route('/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
@moderator_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'success': True})
