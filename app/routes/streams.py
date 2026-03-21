"""Live streaming blueprint — /live"""
import os, uuid
from datetime import datetime, timezone
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, abort, current_app)
from flask_login import login_required, current_user
from app import db, limiter
from app.models import Stream, StreamMessage, Category, Notification
import bleach

streams_bp = Blueprint('streams', __name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _stream_or_404(stream_id):
    return Stream.query.get_or_404(stream_id)


def _sanitize(text, maxlen=500):
    return bleach.clean(text, tags=[], strip=True)[:maxlen].strip()


# ── pages ─────────────────────────────────────────────────────────────────────

@streams_bp.route('/')
def index():
    """All live/recent streams"""
    live    = Stream.query.filter_by(status='live').order_by(
                  Stream.viewer_count.desc()).all()
    recent  = Stream.query.filter_by(status='ended').order_by(
                  Stream.ended_at.desc()).limit(20).all()
    return render_template('streams/index.html', live=live, recent=recent)


@streams_bp.route('/go-live', methods=['GET', 'POST'])
@login_required
def go_live():
    """Create / configure a stream, get stream key"""
    # Find or create an offline stream for this user
    stream = Stream.query.filter_by(user_id=current_user.id,
                                    status='offline').first()

    if request.method == 'POST':
        title       = _sanitize(request.form.get('title', ''), 200)
        description = _sanitize(request.form.get('description', ''), 1000)
        category_id = request.form.get('category_id', type=int)

        if not title:
            flash('Укажите название трансляции.', 'error')
            return redirect(url_for('streams.go_live'))

        if stream is None:
            stream = Stream(user_id=current_user.id)
            stream.generate_key()
            db.session.add(stream)

        stream.title       = title
        stream.description = description
        stream.category_id = category_id
        stream.status      = 'offline'
        db.session.commit()

        flash('Трансляция настроена! Скопируйте ключ и начните стриминг.', 'success')
        return redirect(url_for('streams.dashboard', stream_id=stream.id))

    categories = Category.query.all()
    return render_template('streams/go_live.html', stream=stream,
                           categories=categories)


@streams_bp.route('/<int:stream_id>/dashboard')
@login_required
def dashboard(stream_id):
    stream = _stream_or_404(stream_id)
    if stream.user_id != current_user.id and not current_user.is_moderator:
        abort(403)
    rtmp_url = f"rtmp://localhost:1935/live"
    return render_template('streams/dashboard.html', stream=stream,
                           rtmp_url=rtmp_url)


@streams_bp.route('/watch/<int:stream_id>')
def watch(stream_id):
    stream = _stream_or_404(stream_id)
    if stream.status not in ('live', 'ended'):
        flash('Трансляция ещё не началась.', 'info')
        return redirect(url_for('streams.index'))
    messages = stream.messages.filter_by(is_hidden=False).order_by(
        StreamMessage.created_at.asc()).limit(100).all()
    return render_template('streams/watch.html', stream=stream,
                           messages=messages)


# ── API (AJAX) ────────────────────────────────────────────────────────────────

@streams_bp.route('/<int:stream_id>/start', methods=['POST'])
@login_required
def start_stream(stream_id):
    """Simulate stream going live (in production: triggered by nginx-rtmp)"""
    stream = _stream_or_404(stream_id)
    if stream.user_id != current_user.id:
        return jsonify({'error': 'Нет доступа'}), 403
    if stream.status == 'live':
        return jsonify({'error': 'Уже идёт'}), 400

    stream.status     = 'live'
    stream.started_at = datetime.now(timezone.utc)
    db.session.commit()

    # Notify subscribers
    for sub in current_user.subscribers.all():
        db.session.add(Notification(
            user_id=sub.id, actor_id=current_user.id,
            type='stream',
            message=f'{current_user.display_name} начал трансляцию: {stream.title}',
            url=url_for('streams.watch', stream_id=stream.id)
        ))
    db.session.commit()

    return jsonify({'status': 'live',
                    'watch_url': url_for('streams.watch', stream_id=stream.id)})


@streams_bp.route('/<int:stream_id>/end', methods=['POST'])
@login_required
def end_stream(stream_id):
    stream = _stream_or_404(stream_id)
    if stream.user_id != current_user.id and not current_user.is_moderator:
        return jsonify({'error': 'Нет доступа'}), 403

    stream.status   = 'ended'
    stream.ended_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({'status': 'ended'})


@streams_bp.route('/<int:stream_id>/viewers', methods=['POST'])
def update_viewers(stream_id):
    """Called by client poll to keep viewer count fresh"""
    stream = Stream.query.get_or_404(stream_id)
    delta  = request.json.get('delta', 1)          # +1 join / -1 leave
    stream.viewer_count = max(0, stream.viewer_count + delta)
    if stream.viewer_count > stream.peak_viewers:
        stream.peak_viewers = stream.viewer_count
    db.session.commit()
    return jsonify({'viewer_count': stream.viewer_count})


@streams_bp.route('/<int:stream_id>/chat', methods=['GET', 'POST'])
def chat(stream_id):
    stream = Stream.query.get_or_404(stream_id)

    if request.method == 'POST':
        if not current_user.is_authenticated:
            return jsonify({'error': 'Войдите для чата'}), 401
        if stream.status != 'live':
            return jsonify({'error': 'Трансляция не активна'}), 400

        content = _sanitize(request.json.get('content', ''))
        if not content:
            return jsonify({'error': 'Пустое сообщение'}), 400

        msg = StreamMessage(stream_id=stream_id,
                            user_id=current_user.id,
                            content=content)
        db.session.add(msg)
        db.session.commit()

        return jsonify({
            'id':         msg.id,
            'content':    msg.content,
            'author':     msg.author.display_name or msg.author.username,
            'username':   msg.author.username,
            'avatar':     msg.author.avatar,
            'created_at': msg.created_at.isoformat()
        })

    # GET — fetch latest messages since a given id
    since = request.args.get('since', 0, type=int)
    msgs  = stream.messages.filter(
        StreamMessage.id > since,
        StreamMessage.is_hidden == False
    ).order_by(StreamMessage.created_at.asc()).limit(50).all()

    return jsonify([{
        'id':         m.id,
        'content':    m.content,
        'author':     m.author.display_name or m.author.username,
        'username':   m.author.username,
        'avatar':     m.author.avatar,
        'created_at': m.created_at.isoformat()
    } for m in msgs])


@streams_bp.route('/<int:stream_id>/regenerate-key', methods=['POST'])
@login_required
def regenerate_key(stream_id):
    stream = _stream_or_404(stream_id)
    if stream.user_id != current_user.id:
        return jsonify({'error': 'Нет доступа'}), 403
    stream.generate_key()
    db.session.commit()
    return jsonify({'stream_key': stream.stream_key})
