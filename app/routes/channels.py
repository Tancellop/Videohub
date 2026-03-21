"""Collaborative channels blueprint — /channels"""
import os, uuid, re
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, abort, current_app)
from flask_login import login_required, current_user
from app import db
from app.models import (Channel, ChannelMember, ChannelVideo,
                        ChannelSubscription, Video, Notification, User)
from app.utils.validators import allowed_file, sanitize_input
from sqlalchemy import desc

channels_bp = Blueprint('channels', __name__)

ROLES_HIERARCHY = {'owner': 3, 'admin': 2, 'editor': 1}


def _role_gte(user_role, required):
    return ROLES_HIERARCHY.get(user_role, 0) >= ROLES_HIERARCHY.get(required, 99)


def _make_slug(name):
    slug = re.sub(r'[^\w\s-]', '', name.lower())
    slug = re.sub(r'[-\s]+', '-', slug).strip('-')[:80]
    return slug


# ── pages ─────────────────────────────────────────────────────────────────────

@channels_bp.route('/')
def index():
    """Discover public channels"""
    page     = request.args.get('page', 1, type=int)
    q        = request.args.get('q', '').strip()
    query    = Channel.query
    if q:
        query = query.filter(Channel.name.ilike(f'%{q}%'))
    channels = query.order_by(desc(Channel.created_at)).paginate(
                   page=page, per_page=16, error_out=False)
    return render_template('channels/index.html', channels=channels, q=q)


@channels_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        name        = sanitize_input(request.form.get('name', '').strip(), 100)
        description = sanitize_input(request.form.get('description', '').strip(), 500)

        if not name or len(name) < 2:
            flash('Название канала минимум 2 символа.', 'error')
            return redirect(request.url)

        slug = _make_slug(name)
        if not slug:
            slug = f'channel-{uuid.uuid4().hex[:8]}'

        # Ensure unique slug
        base, counter = slug, 1
        while Channel.query.filter_by(slug=slug).first():
            slug = f'{base}-{counter}'
            counter += 1

        ch = Channel(name=name, slug=slug,
                     description=description, owner_id=current_user.id)
        db.session.add(ch)
        db.session.flush()

        # Add owner as member with role 'owner'
        db.session.add(ChannelMember(channel_id=ch.id,
                                     user_id=current_user.id,
                                     role='owner'))

        # Avatar upload
        if 'avatar' in request.files:
            avatar = request.files['avatar']
            if avatar.filename and allowed_file(
                    avatar.filename, current_app.config['ALLOWED_IMAGE_EXTENSIONS']):
                ext  = avatar.filename.rsplit('.', 1)[1].lower()
                fn   = f'ch_{ch.id}_{uuid.uuid4().hex[:8]}.{ext}'
                adir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'channel_avatars')
                os.makedirs(adir, exist_ok=True)
                avatar.save(os.path.join(adir, fn))
                ch.avatar = fn

        db.session.commit()
        flash(f'Канал «{name}» создан!', 'success')
        return redirect(url_for('channels.view', slug=ch.slug))

    return render_template('channels/create.html')


@channels_bp.route('/<slug>')
def view(slug):
    ch   = Channel.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    cvs  = ChannelVideo.query.filter_by(channel_id=ch.id).order_by(
               desc(ChannelVideo.posted_at)).paginate(
               page=page, per_page=12, error_out=False)

    user_role    = ch.get_member_role(current_user) if current_user.is_authenticated else None
    is_subscribed = False
    if current_user.is_authenticated:
        is_subscribed = ChannelSubscription.query.filter_by(
            channel_id=ch.id, user_id=current_user.id).first() is not None

    return render_template('channels/view.html', ch=ch, cvs=cvs,
                           user_role=user_role, is_subscribed=is_subscribed)


@channels_bp.route('/<slug>/manage', methods=['GET', 'POST'])
@login_required
def manage(slug):
    ch        = Channel.query.filter_by(slug=slug).first_or_404()
    user_role = ch.get_member_role(current_user)
    if not _role_gte(user_role, 'admin'):
        abort(403)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_info' and _role_gte(user_role, 'admin'):
            ch.name        = sanitize_input(request.form.get('name', ch.name), 100)
            ch.description = sanitize_input(request.form.get('description', ''), 500)
            db.session.commit()
            flash('Информация обновлена.', 'success')

        elif action == 'upload_banner' and _role_gte(user_role, 'admin'):
            if 'banner' in request.files:
                f = request.files['banner']
                if f.filename and allowed_file(
                        f.filename, current_app.config['ALLOWED_IMAGE_EXTENSIONS']):
                    ext  = f.filename.rsplit('.', 1)[1].lower()
                    fn   = f'chbanner_{ch.id}_{uuid.uuid4().hex[:8]}.{ext}'
                    bdir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'channel_banners')
                    os.makedirs(bdir, exist_ok=True)
                    f.save(os.path.join(bdir, fn))
                    ch.banner = fn
                    db.session.commit()
                    flash('Баннер обновлён.', 'success')

        elif action == 'invite_member' and _role_gte(user_role, 'admin'):
            username = request.form.get('username', '').strip()
            role     = request.form.get('role', 'editor')
            if role not in ('editor', 'admin'):
                role = 'editor'
            target = User.query.filter_by(username=username).first()
            if not target:
                flash(f'Пользователь @{username} не найден.', 'error')
            elif ch.get_member_role(target):
                flash('Пользователь уже в команде.', 'warning')
            else:
                db.session.add(ChannelMember(channel_id=ch.id,
                                             user_id=target.id, role=role))
                db.session.add(Notification(
                    user_id=target.id, actor_id=current_user.id,
                    type='channel_invite',
                    message=f'{current_user.display_name} добавил вас в канал «{ch.name}» как {role}',
                    url=url_for('channels.view', slug=ch.slug)
                ))
                db.session.commit()
                flash(f'@{username} добавлен как {role}.', 'success')

        elif action == 'remove_member' and _role_gte(user_role, 'admin'):
            member_id = request.form.get('member_id', type=int)
            m = ChannelMember.query.filter_by(channel_id=ch.id,
                                              user_id=member_id).first()
            if m and m.role != 'owner':
                db.session.delete(m)
                db.session.commit()
                flash('Участник удалён.', 'info')

        elif action == 'post_video' and _role_gte(user_role, 'editor'):
            video_id = request.form.get('video_id', type=int)
            video    = db.session.get(Video, video_id)
            if not video:
                flash('Видео не найдено.', 'error')
            elif ChannelVideo.query.filter_by(channel_id=ch.id,
                                              video_id=video_id).first():
                flash('Видео уже добавлено.', 'warning')
            else:
                db.session.add(ChannelVideo(channel_id=ch.id,
                                            video_id=video_id,
                                            posted_by=current_user.id))
                db.session.commit()
                flash('Видео добавлено на канал.', 'success')

        return redirect(url_for('channels.manage', slug=ch.slug))

    members = ChannelMember.query.filter_by(channel_id=ch.id).all()
    # Videos the current user can post (their own published videos)
    my_videos = Video.query.filter_by(
        user_id=current_user.id, status='published').limit(50).all()

    return render_template('channels/manage.html', ch=ch, members=members,
                           my_videos=my_videos, user_role=user_role)


# ── subscriptions & API ───────────────────────────────────────────────────────

@channels_bp.route('/<slug>/subscribe', methods=['POST'])
@login_required
def subscribe(slug):
    ch  = Channel.query.filter_by(slug=slug).first_or_404()
    sub = ChannelSubscription.query.filter_by(
        channel_id=ch.id, user_id=current_user.id).first()

    if sub:
        db.session.delete(sub)
        action = 'unsubscribed'
    else:
        db.session.add(ChannelSubscription(channel_id=ch.id,
                                           user_id=current_user.id))
        action = 'subscribed'

    db.session.commit()
    return jsonify({'action': action, 'count': ch.subscriber_count()})


@channels_bp.route('/avatar/<filename>')
def serve_avatar(filename):
    from flask import send_from_directory
    adir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'channel_avatars')
    return send_from_directory(adir, filename)


@channels_bp.route('/banner/<filename>')
def serve_banner(filename):
    from flask import send_from_directory
    bdir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'channel_banners')
    return send_from_directory(bdir, filename)
