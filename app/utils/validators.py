import re
import bleach


def validate_password(password):
    if len(password) < 8:
        return 'Пароль должен быть не менее 8 символов.'
    if not re.search(r'[a-zA-Z]', password):
        return 'Пароль должен содержать хотя бы одну букву.'
    if not re.search(r'\d', password):
        return 'Пароль должен содержать хотя бы одну цифру.'
    return None


def sanitize_input(text, max_length=None):
    clean = bleach.clean(str(text or ''), tags=[], strip=True).strip()
    if max_length:
        clean = clean[:max_length]
    return clean


def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions
