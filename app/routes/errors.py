from flask import render_template, jsonify, request


def register_errors(app):
    
    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Bad request'}), 400
        return render_template('errors/400.html'), 400
    
    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Forbidden'}), 403
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found'}), 404
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(413)
    def too_large(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'File too large'}), 413
        return render_template('errors/413.html'), 413
    
    @app.errorhandler(429)
    def ratelimit_handler(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Too many requests', 'retry_after': e.description}), 429
        return render_template('errors/429.html'), 429
    
    @app.errorhandler(500)
    def internal_error(e):
        from app import db
        try:
            db.session.rollback()
        except Exception:
            pass
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error'}), 500
        return render_template('errors/500.html'), 500
