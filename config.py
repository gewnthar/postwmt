import os
from dotenv import load_dotenv

# Determine the base directory of the project
basedir = os.path.abspath(os.path.dirname(__file__))
# Load environment variables from .env file located in the base directory
load_dotenv(os.path.join(basedir, '.env'))

# Define the configuration class
class Config:
    # Secret key for session management, loaded from env var or default
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'fallback-secret-key-if-not-set'

    # Database configuration, loaded from env var
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    # Disable modification tracking feature of SQLAlchemy (often not needed and adds overhead)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Google OAuth Configuration, loaded from env vars
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    # Google's discovery document URL for OpenID Connect configuration
    GOOGLE_CONF_URL = 'https://accounts.google.com/.well-known/openid-configuration'
    # Scopes required for Google Sign-In and Calendar access
    GOOGLE_SCOPES = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/calendar.events"
    ]
    # Base URL of the application, loaded from env var (needed for redirects)
    APP_BASE_URL = os.environ.get("APP_BASE_URL")
