import os
import uuid
from flask import (Blueprint, render_template, redirect, url_for, flash, 
                   request, current_app, jsonify, abort, send_from_directory)
from flask_login import login_required, current_user
from app import db, limiter
from app.models import Video, Category, Tag, Comment, Like, ViewHistory, Notification, video_tags
from app.utils.video_processor import process_video, generate_thumbnail
from app.utils.validators import sanitize_input, allowed_file
from sqlalchemy import desc
from datetime import datetime, timezone
import bleach
import re

videos_bp = Blueprint('videos', __name__)


def make_slug(title, video_id=None):
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    slug = slug[:100]
    if video_id:
        slug = f'{slug}-{video_id}'
    return slug


def get_or_create_tag(name):
    name = name.strip().lower()[:50]
    if not name:
        return None
    slug = re.sub(r'[^\w\s-]', '', name)
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')
    tag = Tag.query.filter_by(slug=slug).first()
    if not tag:
        tag = Tag(name=name, slug=slug)
        db.session.add(tag)
    return tag


@videos_bp.route('/upload', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per hour")
def upload():
    if current_user.is_banned:
        flash('Ваш аккаунт заблокирован. Загрузка видео недоступна.', 'error')
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        if 'video' not in request.files:
            flash('Видеофайл не выбран.', 'error')
            return redirect(request.url)
        
        file = request.files['video']
        if file.filename == '':
            flash('Видеофайл не выбран.', 'error')
            return redirect(request.url)
        
        if not allowed_file(file.filename, current_app.config['ALLOWED_VIDEO_EXTENSIONS']):
            flash('Недопустимый формат файла. Разрешены: mp4, avi, mov, mkv, webm, flv, wmv', 'error')
            return redirect(request.url)
        
        title = sanitize_input(request.form.get('title', '').strip())
        description = bleach.clean(
            request.form.get('description', ''), 
            tags=['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'a'],
            attributes={'a': ['href']},
            strip=True
        )
        category_id = request.form.get('category_id', type=int)
        tags_str = request.form.get('tags', '')
        visibility = request.form.get('visibility', 'public')
        
        if not title:
            flash('Заголовок видео обязателен.', 'error')
            return redirect(request.url)
        
        # Save file
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f'{uuid.uuid4().hex}.{ext}'
        filepath = os.path.join(current_app.config['VIDEO_FOLDER'], unique_filename)
        file.save(filepath)
        
        file_size = os.path.getsize(filepath)
        
        # Create video record
        video = Video(
            title=title,
            description=description,
            filename=unique_filename,
            user_id=current_user.id,
            category_id=category_id,
            visibility=visibility,
            file_size=file_size,
            status='processing'
        )
        db.session.add(video)
        db.session.flush()  # Get ID
        
        video.slug = make_slug(title, video.id)
        
        # Process tags
        if tags_str:
            tag_names = [t.strip() for t in tags_str.split(',')][:10]
            for tag_name in tag_names:
                tag = get_or_create_tag(tag_name)
                if tag and tag not in video.tags:
                    video.tags.append(tag)
        
        db.session.commit()
        
        # Process video (thumbnail + metadata)
        try:
            process_video(video, filepath, current_app.config)
            flash('Видео успешно загружено и обрабатывается!', 'success')
        except Exception as e:
            current_app.logger.error(f'Video processing error: {e}')
            video.status = 'published'
            video.published_at = datetime.now(timezone.utc)
            db.session.commit()
            flash('Видео загружено (обработка в упрощённом режиме).', 'success')
        
        # Notify subscribers
        for subscriber in current_user.subscribers.all():
            notif = Notification(
                user_id=subscriber.id,
                actor_id=current_user.id,
                type='upload',
                message=f'{current_user.display_name} загрузил новое видео: {title}',
                url=url_for('videos.watch', slug=video.slug)
            )
            db.session.add(notif)
        db.session.commit()
        
        return redirect(url_for('videos.watch', slug=video.slug))
    
    categories = Category.query.all()
    return render_template('videos/upload.html', categories=categories)


@videos_bp.route('/watch/<slug>')
def watch(slug):
    video = Video.query.filter_by(slug=slug).first_or_404()

    # Restrict access to unpublished or private videos
    if video.status != 'published' or video.visibility == 'private':
        if not current_user.is_authenticated or \
           (current_user.id != video.user_id and not current_user.is_moderator):
            abort(403)

    # Track view — deduplicate by IP within the last 24 hours
    ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    session_id = request.cookies.get('session')

    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    existing = ViewHistory.query.filter_by(
        video_id=video.id,
        ip_address=ip
    ).filter(ViewHistory.created_at > cutoff).first()

    if not existing:
        video.views += 1
        view = ViewHistory(
            video_id=video.id,
            user_id=current_user.id if current_user.is_authenticated else None,
            ip_address=ip,
            session_id=session_id
        )
        db.session.add(view)
        db.session.commit()
    
    # Get comments
    comments = Comment.query.filter_by(
        video_id=video.id, 
        parent_id=None,
        is_hidden=False
    ).order_by(desc(Comment.is_pinned), desc(Comment.created_at)).all()
    
    # Related videos
    related = Video.query.filter(
        Video.id != video.id,
        Video.status == 'published',
        Video.visibility == 'public'
    )
    if video.category_id:
        related = related.filter_by(category_id=video.category_id)
    related = related.order_by(desc(Video.views)).limit(8).all()
    
    user_like = None
    if current_user.is_authenticated:
        like = Like.query.filter_by(user_id=current_user.id, video_id=video.id).first()
        user_like = like.is_like if like else None
        is_subscribed = current_user.is_subscribed_to(video.author)
    else:
        is_subscribed = False
    
    return render_template('videos/watch.html',
                           video=video,
                           comments=comments,
                           related=related,
                           user_like=user_like,
                           is_subscribed=is_subscribed)


@videos_bp.route('/<int:video_id>/like', methods=['POST'])
@login_required
def like_video(video_id):
    video = Video.query.get_or_404(video_id)
    is_like = request.json.get('is_like', True)
    
    existing = Like.query.filter_by(user_id=current_user.id, video_id=video_id).first()
    
    if existing:
        if existing.is_like == is_like:
            db.session.delete(existing)
            action = 'removed'
        else:
            existing.is_like = is_like
            action = 'updated'
    else:
        like = Like(user_id=current_user.id, video_id=video_id, is_like=is_like)
        db.session.add(like)
        action = 'added'
        
        if is_like and video.user_id != current_user.id:
            notif = Notification(
                user_id=video.user_id,
                actor_id=current_user.id,
                type='like',
                message=f'{current_user.display_name} оценил ваше видео "{video.title}"',
                url=url_for('videos.watch', slug=video.slug)
            )
            db.session.add(notif)
    
    db.session.commit()
    
    return jsonify({
        'action': action,
        'likes': video.like_count(),
        'dislikes': video.dislike_count()
    })


@videos_bp.route('/<int:video_id>/comment', methods=['POST'])
@login_required
@limiter.limit("30 per hour")
def add_comment(video_id):
    video = Video.query.get_or_404(video_id)

    body = request.get_json(silent=True) or {}
    content = bleach.clean(body.get('content', '').strip(), tags=[], strip=True)
    parent_id = body.get('parent_id')

    if not content or len(content) > 2000:
        return jsonify({'error': 'Комментарий должен быть от 1 до 2000 символов.'}), 400

    comment = Comment(
        content=content,
        user_id=current_user.id,
        video_id=video_id,
        parent_id=parent_id
    )
    db.session.add(comment)

    # Notify video owner
    if video.user_id != current_user.id:
        notif = Notification(
            user_id=video.user_id,
            actor_id=current_user.id,
            type='comment',
            message=f'{current_user.display_name or current_user.username} прокомментировал ваше видео "{video.title}"',
            url=url_for('videos.watch', slug=video.slug)
        )
        db.session.add(notif)

    db.session.commit()

    return jsonify({
        'id': comment.id,
        'content': comment.content,
        'author': comment.author.display_name or comment.author.username,
        'author_username': comment.author.username,
        'avatar': comment.author.avatar or 'default_avatar.png',
        'created_at': comment.created_at.isoformat(),
        'parent_id': comment.parent_id
    })


@videos_bp.route('/comment/<int:comment_id>/delete', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    
    if comment.user_id != current_user.id and not current_user.is_moderator:
        return jsonify({'error': 'Недостаточно прав.'}), 403
    
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'success': True})


@videos_bp.route('/<int:video_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(video_id):
    video = Video.query.get_or_404(video_id)
    
    if video.user_id != current_user.id and not current_user.is_moderator:
        abort(403)
    
    if request.method == 'POST':
        video.title = sanitize_input(request.form.get('title', '').strip())
        video.description = bleach.clean(
            request.form.get('description', ''),
            tags=['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'a'],
            attributes={'a': ['href']},
            strip=True
        )
        video.category_id = request.form.get('category_id', type=int)
        video.visibility = request.form.get('visibility', 'public')
        
        # Update tags
        tags_str = request.form.get('tags', '')
        video.tags = []
        if tags_str:
            for tag_name in [t.strip() for t in tags_str.split(',')][:10]:
                tag = get_or_create_tag(tag_name)
                if tag:
                    video.tags.append(tag)
        
        # Custom thumbnail
        if 'thumbnail' in request.files:
            thumb = request.files['thumbnail']
            if thumb.filename and allowed_file(thumb.filename, current_app.config['ALLOWED_IMAGE_EXTENSIONS']):
                ext = thumb.filename.rsplit('.', 1)[1].lower()
                thumb_filename = f'{video.id}_{uuid.uuid4().hex}.{ext}'
                thumb_path = os.path.join(current_app.config['THUMBNAIL_FOLDER'], thumb_filename)
                thumb.save(thumb_path)
                video.thumbnail = thumb_filename
        
        db.session.commit()
        flash('Видео обновлено!', 'success')
        return redirect(url_for('videos.watch', slug=video.slug))
    
    categories = Category.query.all()
    return render_template('videos/edit.html', video=video, categories=categories)


@videos_bp.route('/<int:video_id>/delete', methods=['DELETE', 'POST'])
@login_required
def delete(video_id):
    video = Video.query.get_or_404(video_id)
    
    if video.user_id != current_user.id and not current_user.is_moderator:
        abort(403)
    
    # Delete files
    try:
        filepath = os.path.join(current_app.config['VIDEO_FOLDER'], video.filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        if video.thumbnail:
            thumb_path = os.path.join(current_app.config['THUMBNAIL_FOLDER'], video.thumbnail)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
    except Exception as e:
        current_app.logger.error(f'File deletion error: {e}')
    
    db.session.delete(video)
    db.session.commit()
    
    if request.method == 'DELETE':
        return jsonify({'success': True})
    
    flash('Видео удалено.', 'info')
    return redirect(url_for('users.profile', username=current_user.username))


@videos_bp.route('/serve/<filename>')
def serve_video(filename):
    return send_from_directory(current_app.config['VIDEO_FOLDER'], filename)


@videos_bp.route('/thumbnail/<filename>')
def serve_thumbnail(filename):
    return send_from_directory(current_app.config['THUMBNAIL_FOLDER'], filename)


@videos_bp.route('/comment/<int:comment_id>/like', methods=['POST'])
@login_required
def like_comment(comment_id):
    from app.models import CommentLike
    comment = Comment.query.get_or_404(comment_id)
    existing = CommentLike.query.filter_by(
        user_id=current_user.id, comment_id=comment_id).first()
    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(CommentLike(user_id=current_user.id, comment_id=comment_id))
        liked = True
    db.session.commit()
    count = CommentLike.query.filter_by(comment_id=comment_id).count()
    return jsonify({'liked': liked, 'count': count})


@videos_bp.route('/<int:video_id>/comments')
def get_comments(video_id):
    """AJAX: load comments with sort + pagination"""
    from app.models import CommentLike
    video  = Video.query.get_or_404(video_id)
    sort   = request.args.get('sort', 'top')
    page   = request.args.get('page', 1, type=int)
    query  = Comment.query.filter_by(video_id=video_id, parent_id=None, is_hidden=False)

    if sort == 'new':
        query = query.order_by(Comment.created_at.desc())
    elif sort == 'old':
        query = query.order_by(Comment.created_at.asc())
    else:  # top
        query = query.order_by(Comment.is_pinned.desc(), Comment.created_at.desc())

    paginated = query.paginate(page=page, per_page=20, error_out=False)

    liked_ids = set()
    if current_user.is_authenticated:
        cids = [c.id for c in paginated.items]
        liked_ids = {cl.comment_id for cl in
                     CommentLike.query.filter(
                         CommentLike.user_id == current_user.id,
                         CommentLike.comment_id.in_(cids)).all()}

    def serialize(c, is_reply=False):
        from app.models import CommentLike as CL
        lc = CL.query.filter_by(comment_id=c.id).count()
        replies_data = []
        if not is_reply:
            for r in c.replies.filter_by(is_hidden=False).order_by(Comment.created_at.asc()).limit(50).all():
                replies_data.append(serialize(r, is_reply=True))
        return {
            'id':            c.id,
            'content':       c.content,
            'created_at':    c.created_at.isoformat(),
            'author':        c.author.display_name or c.author.username,
            'author_username': c.author.username,
            'avatar':        c.author.avatar or 'default_avatar.png',
            'is_pinned':     c.is_pinned,
            'parent_id':     c.parent_id,
            'like_count':    lc,
            'liked':         c.id in liked_ids,
            'can_delete':    current_user.is_authenticated and (
                             current_user.id == c.user_id or current_user.is_moderator),
            'replies':       replies_data,
            'reply_count':   c.replies.filter_by(is_hidden=False).count() if not is_reply else 0,
        }

    return jsonify({
        'comments': [serialize(c) for c in paginated.items],
        'total':    paginated.total,
        'pages':    paginated.pages,
        'page':     page,
    })
