import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, Video, Notification, subscriptions, Playlist, PlaylistItem
from app.utils.validators import allowed_file
from sqlalchemy import desc

users_bp = Blueprint('users', __name__)


@users_bp.route('/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    if user.is_banned and not (current_user.is_authenticated and current_user.is_moderator):
        abort(404)
    
    page = request.args.get('page', 1, type=int)
    tab = request.args.get('tab', 'videos')
    
    videos = Video.query.filter_by(user_id=user.id, status='published')
    
    if current_user.is_authenticated and current_user.id == user.id:
        videos = Video.query.filter_by(user_id=user.id).filter(
            Video.status.in_(['published', 'draft'])
        )
    else:
        videos = videos.filter_by(visibility='public')
    
    videos = videos.order_by(desc(Video.published_at)).paginate(page=page, per_page=12, error_out=False)
    
    is_subscribed = False
    if current_user.is_authenticated and current_user.id != user.id:
        is_subscribed = current_user.is_subscribed_to(user)
    
    playlists = []
    if tab == 'playlists':
        playlists = Playlist.query.filter_by(user_id=user.id, visibility='public').all()
    
    return render_template('users/profile.html',
                           user=user,
                           videos=videos,
                           is_subscribed=is_subscribed,
                           tab=tab,
                           playlists=playlists)


@users_bp.route('/subscribe/<int:user_id>', methods=['POST'])
@login_required
def subscribe(user_id):
    channel = User.query.get_or_404(user_id)
    
    if channel.id == current_user.id:
        return jsonify({'error': 'Нельзя подписаться на себя.'}), 400
    
    if current_user.is_subscribed_to(channel):
        current_user.subscribed_to.remove(channel)
        action = 'unsubscribed'
    else:
        current_user.subscribed_to.append(channel)
        action = 'subscribed'
        
        notif = Notification(
            user_id=channel.id,
            actor_id=current_user.id,
            type='subscribe',
            message=f'{current_user.display_name} подписался на ваш канал',
            url=url_for('users.profile', username=current_user.username)
        )
        db.session.add(notif)
    
    db.session.commit()
    
    return jsonify({
        'action': action,
        'subscriber_count': channel.subscriber_count()
    })


@users_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'profile':
            current_user.display_name = request.form.get('display_name', '').strip()[:100]
            current_user.bio = request.form.get('bio', '').strip()[:500]
            
            # Avatar upload
            if 'avatar' in request.files:
                avatar = request.files['avatar']
                if avatar.filename and allowed_file(avatar.filename, current_app.config['ALLOWED_IMAGE_EXTENSIONS']):
                    avatar_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'avatars')
                    os.makedirs(avatar_dir, exist_ok=True)
                    ext = avatar.filename.rsplit('.', 1)[1].lower()
                    filename = f'{current_user.id}_{uuid.uuid4().hex}.{ext}'
                    avatar.save(os.path.join(avatar_dir, filename))
                    current_user.avatar = filename
            
            db.session.commit()
            flash('Профиль обновлён!', 'success')
        
        elif action == 'banner':
            if 'banner' in request.files:
                banner = request.files['banner']
                if banner.filename and allowed_file(banner.filename, current_app.config['ALLOWED_IMAGE_EXTENSIONS']):
                    banner_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'banners')
                    os.makedirs(banner_dir, exist_ok=True)
                    ext = banner.filename.rsplit('.', 1)[1].lower()
                    filename = f'{current_user.id}_banner_{uuid.uuid4().hex[:8]}.{ext}'
                    
                    # Resize banner to 2560×1440 max using Pillow
                    try:
                        from PIL import Image as PILImage
                        import io
                        img = PILImage.open(banner)
                        img.thumbnail((2560, 1440), PILImage.LANCZOS)
                        # Convert to RGB if needed (e.g. PNG with alpha)
                        if img.mode in ('RGBA', 'P'):
                            bg = PILImage.new('RGB', img.size, (20, 20, 30))
                            bg.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
                            img = bg
                        out_path = os.path.join(banner_dir, filename)
                        img.save(out_path, 'JPEG', quality=90)
                        current_user.banner = filename
                        flash('Баннер обновлён!', 'success')
                    except Exception as e:
                        current_app.logger.error(f'Banner processing error: {e}')
                        # Fallback: save as-is
                        banner.seek(0)
                        banner.save(os.path.join(banner_dir, filename))
                        current_user.banner = filename
                        flash('Баннер обновлён!', 'success')
                else:
                    flash('Неверный формат. Используйте JPG, PNG или GIF.', 'error')
            
            db.session.commit()
            return redirect(url_for('users.settings'))

        elif action == 'delete_banner':
            if current_user.banner:
                try:
                    banner_path = os.path.join(
                        current_app.config['UPLOAD_FOLDER'], 'banners', current_user.banner
                    )
                    if os.path.exists(banner_path):
                        os.remove(banner_path)
                except Exception:
                    pass
                current_user.banner = None
                db.session.commit()
                flash('Баннер удалён.', 'info')
            return redirect(url_for('users.settings'))

        elif action == 'password':
            current_pw = request.form.get('current_password')
            new_pw = request.form.get('new_password')
            confirm = request.form.get('confirm_password')

            if not current_user.check_password(current_pw):
                flash('Неверный текущий пароль.', 'error')
            elif new_pw != confirm:
                flash('Новые пароли не совпадают.', 'error')
            elif len(new_pw) < 8:
                flash('Пароль должен быть не менее 8 символов.', 'error')
            else:
                current_user.set_password(new_pw)
                db.session.commit()
                flash('Пароль изменён!', 'success')
        
        return redirect(url_for('users.settings'))
    
    return render_template('users/settings.html')


@users_bp.route('/notifications')
@login_required
def notifications():
    page = request.args.get('page', 1, type=int)
    notifs = Notification.query.filter_by(user_id=current_user.id)\
                               .order_by(desc(Notification.created_at))\
                               .paginate(page=page, per_page=20, error_out=False)
    
    # Mark as read
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    
    return render_template('users/notifications.html', notifications=notifs)


@users_bp.route('/notifications/count')
@login_required
def notification_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})


@users_bp.route('/history')
@login_required
def history():
    from app.models import ViewHistory
    from sqlalchemy import distinct
    
    page = request.args.get('page', 1, type=int)
    history = db.session.query(ViewHistory).filter_by(user_id=current_user.id)\
                        .order_by(desc(ViewHistory.created_at))\
                        .paginate(page=page, per_page=12, error_out=False)
    
    return render_template('users/history.html', history=history)


@users_bp.route('/banner/<filename>')
def serve_banner(filename):
    from flask import send_from_directory, current_app
    banner_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'banners')
    return send_from_directory(banner_dir, filename)


@users_bp.route('/subscriptions')
@login_required
def subscriptions_feed():
    page = request.args.get('page', 1, type=int)
    subscribed_ids = [u.id for u in current_user.subscribed_to.all()]
    
    videos = Video.query.filter(
        Video.user_id.in_(subscribed_ids),
        Video.status == 'published',
        Video.visibility == 'public'
    ).order_by(desc(Video.published_at)).paginate(page=page, per_page=12, error_out=False)
    
    return render_template('users/subscriptions.html', videos=videos)
