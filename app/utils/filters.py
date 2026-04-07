from datetime import datetime, timezone


def register_filters(app):
    @app.template_filter('timeago')
    def timeago_filter(dt):
        if not dt: return 'нет данных'
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        diff = (datetime.now(timezone.utc) - dt).total_seconds()
        if diff < 60: return 'только что'
        if diff < 3600: return f'{int(diff/60)} мин. назад'
        if diff < 86400: return f'{int(diff/3600)} ч. назад'
        if diff < 604800: return f'{int(diff/86400)} дн. назад'
        if diff < 2592000: return f'{int(diff/604800)} нед. назад'
        if diff < 31536000: return f'{int(diff/2592000)} мес. назад'
        return f'{int(diff/31536000)} г. назад'

    @app.template_filter('format_views')
    def format_views(count):
        if count is None: return '0'
        if count < 1000: return str(count)
        if count < 1000000: return f'{count/1000:.1f}K'
        return f'{count/1000000:.1f}M'

    @app.template_filter('format_date')
    def format_date(dt):
        return dt.strftime('%d.%m.%Y') if dt else ''

    @app.template_filter('nl2br')
    def nl2br(text):
        return (text or '').replace('\n', '<br>')

    @app.template_filter('truncate_words')
    def truncate_words(text, length=100):
        if not text or len(text) <= length: return text or ''
        return text[:length].rsplit(' ', 1)[0] + '...'
