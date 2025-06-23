# /var/www/postwmt/app/__init__.py
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from authlib.integrations.flask_client import OAuth
from flask_wtf.csrf import CSRFProtect  # <--- Import CSRFProtect
from config import Config

# --- Initialize extensions globally but unbound ---
db = SQLAlchemy()
migrate = Migrate()
oauth = OAuth()
csrf = CSRFProtect()  # <--- Initialize CSRFProtect

# --- Application Factory Function ---
# This function creates and configures the Flask app instance.
def create_app(config_class=Config):
    # Calculate the absolute path to the project's base directory
    # basedir is directory containing the 'app' package (e.g., /var/www/postwmt)
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    # Create Flask app instance, setting the template folder explicitly
    app = Flask(__name__,
                instance_relative_config=False, # Can explore instance folders later if needed
                template_folder=os.path.join(basedir, 'templates') # Explicit path
               )

    # Load configuration from the Config object (which loads from .env)
    app.config.from_object(config_class)

    # --- Initialize Flask extensions with the app instance ---
    # Now we bind the globally created extension objects to our specific app.
    db.init_app(app)
    migrate.init_app(app, db) # Flask-Migrate needs both app and db
    oauth.init_app(app)
    csrf.init_app(app)  # <--- Initialize CSRFProtect with the app

    # --- Configure Google OAuth client using Authlib ---
    # This uses the GOOGLE_CLIENT_ID etc. loaded from config/env
    oauth.register(
        name='google', # Name used to reference this provider (e.g., oauth.google)
        client_id=app.config.get('GOOGLE_CLIENT_ID'),
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url=app.config.get('GOOGLE_CONF_URL'), # Fetches endpoints from Google
        client_kwargs={
            'scope': ' '.join(app.config.get('GOOGLE_SCOPES', [])) # Define permissions needed
        }
    )

    # --- Import application components within app context ---
    with app.app_context():
        from . import models
    # Import routes so Flask knows about them
        from . import routes # For '/' and '/generate_ics'

    # --- ADD/UNCOMMENT THESE LINES ---
        from . import auth # Import the auth blueprint file
        app.register_blueprint(auth.auth_bp)
        return app

# --- End of /var/www/postwmt/app/__init__.py ---
