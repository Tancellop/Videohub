from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db, mail, limiter
from app.models import User, Notification
from app.utils.validators import validate_password, sanitize_input
from flask_mail import Message
from datetime import datetime, timezone
import re

auth_bp = Blueprint('auth', __name__)


def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = sanitize_input(request.form.get('username', '').strip())
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        errors = []

        if not username or len(username) < 3 or len(username) > 50:
            errors.append('Имя пользователя должно быть от 3 до 50 символов.')

        if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
            errors.append('Имя пользователя может содержать только буквы, цифры, _, . и -')

        if not is_valid_email(email):
            errors.append('Неверный формат email.')

        error_msg = validate_password(password)
        if error_msg:
            errors.append(error_msg)

        if password != confirm_password:
            errors.append('Пароли не совпадают.')

        if User.query.filter_by(username=username).first():
            errors.append('Это имя пользователя уже занято.')

        if User.query.filter_by(email=email).first():
            errors.append('Этот email уже зарегистрирован.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/register.html', username=username, email=email)

        user = User(
            username=username,
            email=email,
            display_name=username,
            is_verified=True
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash('Регистрация успешна! Теперь вы можете войти.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        login_field = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False) == 'on'

        user = None
        if '@' in login_field:
            user = User.query.filter_by(email=login_field.lower()).first()
        else:
            user = User.query.filter_by(username=login_field).first()

        if user and user.check_password(password):
            if user.is_banned:
                flash(f'Ваш аккаунт заблокирован. Причина: {user.ban_reason or "Нарушение правил"}', 'error')
                return render_template('auth/login.html')

            # FIX: Clear old session before login to prevent session fixation
            session.clear()
            login_user(user, remember=remember)
            user.last_seen = datetime.now(timezone.utc)
            db.session.commit()

            next_page = request.args.get('next')
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            return redirect(url_for('main.index'))
        else:
            flash('Неверный логин или пароль.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    # FIX: Don't use @login_required — just handle gracefully if not logged in
    if current_user.is_authenticated:
        logout_user()
    session.clear()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/verify/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        flash('Недействительная или истёкшая ссылка подтверждения.', 'error')
        return redirect(url_for('auth.login'))

    user.is_verified = True
    user.verification_token = None
    db.session.commit()

    flash('Email подтверждён! Теперь вы можете войти.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("3 per hour")
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()

        if user:
            token = user.generate_reset_token()
            db.session.commit()
            try:
                send_reset_email(user, token)
            except Exception as e:
                current_app.logger.error(f'Reset email error: {e}')

        flash('Если такой email существует, ссылка для сброса пароля была отправлена.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()

    if not user or (user.reset_token_expires and
                    user.reset_token_expires < datetime.now(timezone.utc)):
        flash('Недействительная или истёкшая ссылка сброса пароля.', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        error = validate_password(password)
        if error:
            flash(error, 'error')
            return render_template('auth/reset_password.html', token=token)

        if password != confirm:
            flash('Пароли не совпадают.', 'error')
            return render_template('auth/reset_password.html', token=token)

        user.set_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()

        flash('Пароль успешно изменён!', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


def send_verification_email(user, token):
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    msg = Message(
        subject='Подтвердите ваш email — VideoHub',
        recipients=[user.email],
        html=render_template('auth/email_verify.html', user=user, url=verify_url)
    )
    mail.send(msg)


def send_reset_email(user, token):
    reset_url = url_for('auth.reset_password', token=token, _external=True)
    msg = Message(
        subject='Сброс пароля — VideoHub',
        recipients=[user.email],
        html=render_template('auth/email_reset.html', user=user, url=reset_url)
    )
    mail.send(msg)
