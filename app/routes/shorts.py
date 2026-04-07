"""Shorts blueprint — /shorts  (vertical video ≤ 60 sec)"""
import os, uuid, re, tempfile
import cloudinary
import cloudinary.uploader
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, current_app, abort)
from flask_login import login_required, current_user
from app import db, limiter
from app.models import Video, Category, Tag, Like, ViewHistory, Comment
from app.utils.validators import allowed_file, sanitize_input
from sqlalchemy import desc
from datetime import datetime, timezone
import bleach

shorts_bp = Blueprint('shorts', __name__)


def _make_slug(title, vid_id):
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')[:80]
    return f'{slug}-{vid_id}'


def _get_or_create_tag(name):
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


# ── pages ─────────────────────────────────────────────────────────────────────

@shorts_bp.route('/')
def feed():
    """Infinite swipe feed of shorts"""
    page    = request.args.get('page', 1, type=int)
    shorts  = Video.query.filter_by(
        status='published', visibility='public', is_short=True
    ).order_by(desc(Video.views)).paginate(page=page, per_page=10, error_out=False)

    # Precompute user-like status
    liked_ids = set()
    if current_user.is_authenticated:
        liked_ids = {l.video_id for l in
                     current_user.likes.filter_by(is_like=True).all()}

    return render_template('shorts/feed.html', shorts=shorts,
                           liked_ids=liked_ids)


@shorts_bp.route('/upload', methods=['GET', 'POST'])
@login_required
@limiter.limit("20 per hour")
def upload():
    if request.method == 'POST':
        file = request.files.get('video')
        if not file or file.filename == '':
            flash('Выберите видеофайл.', 'error')
            return redirect(request.url)

        if not allowed_file(file.filename,
                            current_app.config['ALLOWED_VIDEO_EXTENSIONS']):
            flash('Недопустимый формат.', 'error')
            return redirect(request.url)

        title   = sanitize_input(request.form.get('title', '').strip())
        tags_str = request.form.get('tags', '')

        if not title:
            flash('Укажите название.', 'error')
            return redirect(request.url)

        ext      = file.filename.rsplit('.', 1)[1].lower()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}')
        file.save(temp_file.name)
        temp_file.close()
        temp_path = temp_file.name

        short = Video(
            title=title,
            filename='',
            user_id=current_user.id,
            visibility='public',
            is_short=True,
            status='processing'
        )
        db.session.add(short)
        db.session.flush()
        short.slug = _make_slug(title, short.id)

        for tag_name in [t.strip() for t in tags_str.split(',')][:10]:
            tag = _get_or_create_tag(tag_name)
            if tag and tag not in short.tags:
                short.tags.append(tag)

        cloudinary.config(
            cloud_name=current_app.config['CLOUDINARY_CLOUD_NAME'],
            api_key=current_app.config['CLOUDINARY_API_KEY'],
            api_secret=current_app.config['CLOUDINARY_API_SECRET'],
        )

        try:
            upload_result = cloudinary.uploader.upload_large(
                temp_path,
                resource_type='video',
                public_id=f'videohub/shorts/{uuid.uuid4().hex}',
                chunk_size=6 * 1024 * 1024,
                overwrite=True
            )
            video_url = upload_result.get('secure_url') or upload_result.get('url')
            if not video_url:
                raise ValueError('Cloudinary upload did not return a video URL')
            short.filename = video_url
            short.file_size = upload_result.get('bytes') or os.path.getsize(temp_path)
        except Exception as e:
            current_app.logger.error(f'Cloudinary upload error: {e}')
            if os.path.exists(temp_path):
                os.remove(temp_path)
            flash('Не удалось загрузить короткое видео. Повторите попытку.', 'error')
            return redirect(request.url)

        db.session.commit()

        # Process (thumbnail + duration detection)
        try:
            from app.utils.video_processor import process_video
            process_video(short, temp_path, current_app.config)
        except Exception as e:
            current_app.logger.error(f'Short processing error: {e}')
            short.status = 'published'
            short.published_at = datetime.now(timezone.utc)
            db.session.commit()
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

        flash('Shorts загружен!', 'success')
        return redirect(url_for('shorts.feed'))

    return render_template('shorts/upload.html')


@shorts_bp.route('/<int:short_id>/like', methods=['POST'])
@login_required
def like_short(short_id):
    short   = Video.query.filter_by(id=short_id, is_short=True).first_or_404()
    is_like = request.json.get('is_like', True)

    existing = Like.query.filter_by(
        user_id=current_user.id, video_id=short_id).first()

    if existing:
        if existing.is_like == is_like:
            db.session.delete(existing)
            liked = False
        else:
            existing.is_like = is_like
            liked = is_like
    else:
        db.session.add(Like(user_id=current_user.id,
                            video_id=short_id, is_like=is_like))
        liked = is_like

    db.session.commit()
    return jsonify({'likes': short.like_count(), 'liked': liked})


@shorts_bp.route('/<int:short_id>/comment', methods=['POST'])
@login_required
@limiter.limit("30 per hour")
def comment_short(short_id):
    short = Video.query.filter_by(id=short_id, is_short=True).first_or_404()

    body = request.get_json(silent=True) or {}
    content = bleach.clean(body.get('content', '').strip(), tags=[], strip=True)

    if not content or len(content) > 500:
        return jsonify({'error': 'Комментарий 1–500 символов'}), 400

    c = Comment(content=content, user_id=current_user.id, video_id=short_id)
    db.session.add(c)
    db.session.commit()

    return jsonify({
        'id':         c.id,
        'content':    c.content,
        'author':     c.author.display_name or c.author.username,
        'avatar':     c.author.avatar or 'default_avatar.png',
        'created_at': c.created_at.isoformat()
    })


@shorts_bp.route('/api/next')
def api_next():
    """Return next batch of shorts (AJAX infinite scroll)"""
    page   = request.args.get('page', 1, type=int)
    shorts = Video.query.filter_by(
        status='published', visibility='public', is_short=True
    ).order_by(desc(Video.views)).paginate(page=page, per_page=5, error_out=False)

    return jsonify([{
        'id':        s.id,
        'title':     s.title,
        'slug':      s.slug,
        'filename':  s.filename,
        'thumbnail': s.thumbnail,
        'likes':     s.like_count(),
        'views':     s.views,
        'author':    s.author.display_name or s.author.username,
        'username':  s.author.username,
        'duration':  s.duration,
        'tags':      [t.name for t in s.tags]
    } for s in shorts.items])
