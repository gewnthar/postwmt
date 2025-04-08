# /var/www/postwmt/app/models.py
from app import db # Import 'db' instance from app/__init__.py
from datetime import datetime, timezone # Import timezone

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Google's unique ID for the user (comes from Google Sign-In)
    google_id = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    # Store the refresh token securely! Needed for offline access to Calendar API.
    # It might be null if the user hasn't granted offline access or revoked it.
    google_refresh_token = db.Column(db.Text, nullable=True)
    # Use timezone.utc for timezone-aware datetime
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        # A helpful representation when printing User objects
        return f'<User {self.email}>'
