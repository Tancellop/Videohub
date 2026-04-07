from flask_login import current_user


def register_context_processors(app):
    @app.context_processor
    def inject_globals():
        from app.models import Category, Notification
        categories = Category.query.all()
        unread = 0
        if current_user.is_authenticated:
            unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return dict(g_categories=categories, unread_notifications=unread)
