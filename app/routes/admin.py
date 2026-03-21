from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user
from app import db
from app.models import User, Video, Comment, Category, Tag, Report, Notification
from sqlalchemy import desc, func
from datetime import datetime, timezone, timedelta
from functools import wraps

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def moderator_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_moderator:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/')
@login_required
@moderator_required
def dashboard():
    # Stats
    total_users = User.query.count()
    total_videos = Video.query.count()
    total_views = db.session.query(func.sum(Video.views)).scalar() or 0
    total_comments = Comment.query.count()
    
    new_users_today = User.query.filter(
        User.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    ).count()
    
    new_videos_today = Video.query.filter(
        Video.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    ).count()
    
    pending_reports = Report.query.filter_by(status='pending').count()
    
    # Recent items
    recent_users = User.query.order_by(desc(User.created_at)).limit(5).all()
    recent_videos = Video.query.order_by(desc(Video.created_at)).limit(5).all()
    
    # Chart data (last 7 days)
    chart_data = []
    for i in range(6, -1, -1):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        users_count = User.query.filter(User.created_at.between(start, end)).count()
        videos_count = Video.query.filter(Video.created_at.between(start, end)).count()
        
        chart_data.append({
            'date': date.strftime('%d.%m'),
            'users': users_count,
            'videos': videos_count
        })
    
    return render_template('admin/dashboard.html',
                           total_users=total_users,
                           total_videos=total_videos,
                           total_views=total_views,
                           total_comments=total_comments,
                           new_users_today=new_users_today,
                           new_videos_today=new_videos_today,
                           pending_reports=pending_reports,
                           recent_users=recent_users,
                           recent_videos=recent_videos,
                           chart_data=chart_data)


@admin_bp.route('/users')
@login_required
@moderator_required
def users():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    role_filter = request.args.get('role', '')
    
    query = User.query
    if search:
        query = query.filter(
            db.or_(User.username.ilike(f'%{search}%'), User.email.ilike(f'%{search}%'))
        )
    if role_filter:
        query = query.filter_by(role=role_filter)
    
    users = query.order_by(desc(User.created_at)).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/users.html', users=users, search=search, role_filter=role_filter)


@admin_bp.route('/users/<int:user_id>/action', methods=['POST'])
@login_required
@moderator_required
def user_action(user_id):
    user = User.query.get_or_404(user_id)
    action = request.json.get('action')
    
    if user.is_admin and not current_user.is_admin:
        return jsonify({'error': 'Недостаточно прав'}), 403
    
    if action == 'ban':
        user.is_banned = True
        user.ban_reason = request.json.get('reason', 'Нарушение правил')
        msg = f'Пользователь {user.username} заблокирован'
    elif action == 'unban':
        user.is_banned = False
        user.ban_reason = None
        msg = f'Пользователь {user.username} разблокирован'
    elif action == 'verify':
        user.is_verified = True
        msg = f'Email пользователя {user.username} подтверждён'
    elif action == 'set_role' and current_user.is_admin:
        role = request.json.get('role', 'user')
        if role in ['user', 'moderator', 'admin']:
            user.role = role
            msg = f'Роль пользователя {user.username} изменена на {role}'
        else:
            return jsonify({'error': 'Неверная роль'}), 400
    elif action == 'delete' and current_user.is_admin:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Пользователь удалён'})
    else:
        return jsonify({'error': 'Неизвестное действие'}), 400
    
    db.session.commit()
    return jsonify({'success': True, 'message': msg})


@admin_bp.route('/videos')
@login_required
@moderator_required
def videos():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    
    query = Video.query
    if search:
        query = query.filter(Video.title.ilike(f'%{search}%'))
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    videos = query.order_by(desc(Video.created_at)).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/videos.html', videos=videos, search=search, status_filter=status_filter)


@admin_bp.route('/videos/<int:video_id>/action', methods=['POST'])
@login_required
@moderator_required
def video_action(video_id):
    video = Video.query.get_or_404(video_id)
    action = request.json.get('action')
    
    if action == 'publish':
        video.status = 'published'
        if not video.published_at:
            video.published_at = datetime.now(timezone.utc)
    elif action == 'unpublish':
        video.status = 'draft'
    elif action == 'delete':
        import os
        from flask import current_app
        try:
            fp = os.path.join(current_app.config['VIDEO_FOLDER'], video.filename)
            if os.path.exists(fp):
                os.remove(fp)
        except:
            pass
        db.session.delete(video)
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Неизвестное действие'}), 400
    
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/categories', methods=['GET', 'POST'])
@login_required
@admin_required
def categories():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create':
            import re
            name = request.form.get('name', '').strip()
            icon = request.form.get('icon', '📹')
            description = request.form.get('description', '')
            slug = re.sub(r'[^\w\s-]', '', name.lower())
            slug = re.sub(r'[-\s]+', '-', slug).strip('-')
            
            if name and not Category.query.filter_by(slug=slug).first():
                cat = Category(name=name, slug=slug, icon=icon, description=description)
                db.session.add(cat)
                db.session.commit()
                flash(f'Категория "{name}" создана.', 'success')
            else:
                flash('Название уже занято или не указано.', 'error')
        
        elif action == 'delete':
            cat_id = request.form.get('category_id', type=int)
            cat = db.session.get(Category, cat_id)
            if cat:
                Video.query.filter_by(category_id=cat.id).update({'category_id': None})
                db.session.delete(cat)
                db.session.commit()
                flash('Категория удалена.', 'info')
        
        return redirect(url_for('admin.categories'))
    
    cats = Category.query.all()
    return render_template('admin/categories.html', categories=cats)


@admin_bp.route('/reports')
@login_required
@moderator_required
def reports():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'pending')
    
    reports = Report.query.filter_by(status=status)\
                          .order_by(desc(Report.created_at))\
                          .paginate(page=page, per_page=20, error_out=False)
    
    return render_template('admin/reports.html', reports=reports, current_status=status)


@admin_bp.route('/reports/<int:report_id>/action', methods=['POST'])
@login_required
@moderator_required
def report_action(report_id):
    report = Report.query.get_or_404(report_id)
    action = request.json.get('action')
    
    if action == 'dismiss':
        report.status = 'dismissed'
    elif action == 'review':
        report.status = 'reviewed'
    
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/stats/api')
@login_required
@moderator_required
def stats_api():
    days = request.args.get('days', 7, type=int)
    data = []
    
    for i in range(days - 1, -1, -1):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = date.replace(hour=23, minute=59, second=59)
        
        data.append({
            'date': date.strftime('%d.%m'),
            'users': User.query.filter(User.created_at.between(start, end)).count(),
            'videos': Video.query.filter(Video.created_at.between(start, end)).count(),
        })
    
    return jsonify(data)
