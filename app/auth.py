import os # Often useful, though maybe not directly here yet
from flask import Blueprint, url_for, redirect, session, current_app, flash
# Import User model and db instance from the main app package (__init__.py)
from .models import User, db
# Import the oauth object initialized in app/__init__.py
# This assumes 'oauth = OAuth()' is defined at the top level in app/__init__.py
from app import oauth

# Create a Blueprint for authentication routes
# 'auth' is the internal name for url_for, __name__ helps locate resources
# url_prefix='/' means routes defined here (like /login) are relative to the root
auth_bp = Blueprint('auth', __name__, url_prefix='/')


@auth_bp.route('/login')
def login():
    """Redirects the user to Google's OAuth 2.0 server to initiate login."""
    # Create the URL for our '/callback' route where Google will send the user back
    # _external=True ensures it's an absolute URL (https://...) required by Google
    redirect_uri = url_for('auth.callback', _external=True)
    current_app.logger.info(f"Redirecting to Google for login. Callback URI: {redirect_uri}")

    # Use the 'google' provider registered in __init__.py to generate the auth URL and redirect
    # This sends the user's browser to Google's login/consent page
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/callback')
def callback():
    """Handles the redirect back from Google after user authentication."""
    current_app.logger.info("Entered /callback route")
    try:
        # Exchange the authorization code (in the incoming request URL) for an access token
        # This happens by making a server-to-server request to Google's token endpoint
        token = oauth.google.authorize_access_token()
        current_app.logger.info("Successfully obtained token from Google.")
        # The 'token' dictionary now holds access_token, refresh_token (maybe), etc.

        # Use the access token to fetch user info from Google's userinfo endpoint
        user_info = oauth.google.userinfo()
        # user_info is a dictionary with keys like 'sub', 'name', 'email', etc.

        # Validate that we got the necessary info (especially 'sub', Google's unique ID)
        if not user_info or 'sub' not in user_info:
             current_app.logger.error("Failed to fetch valid user info from Google userinfo endpoint.")
             flash("Error fetching user info from Google.", "danger")
             return redirect(url_for('index')) # Redirect to main page on error

        # Extract user details
        google_id = user_info.get('sub')
        email = user_info.get('email')
        name = user_info.get('name')
        # Get refresh token IF Google sent one (usually only first time or if prompt=consent)
        refresh_token = token.get('refresh_token')

        current_app.logger.info(f"User info received: google_id={google_id}, email={email}, name={name}, refresh_token_present={bool(refresh_token)}")

        # --- Database Interaction: Find or Create User ---
        user = User.query.filter_by(google_id=google_id).first()

        if user:
            # Existing user found
            user.email = email # Update email/name in case they changed
            user.name = name
            if refresh_token:
                user.google_refresh_token = refresh_token # Update refresh token if we got a new one
                current_app.logger.info(f"Updating refresh token for existing user {email}")
            else:
                current_app.logger.info(f"No new refresh token provided for existing user {email}")
            db.session.commit() # Save changes
            current_app.logger.info(f"Existing user logged in: {email}")
        else:
            # New user - create a record
            new_user = User(
                google_id=google_id,
                email=email,
                name=name,
                google_refresh_token=refresh_token # Store the initial refresh token
            )
            db.session.add(new_user)
            db.session.commit() # Save the new user
            user = new_user # Proceed using the new user object
            current_app.logger.info(f"New user created and logged in: {email}")
        # --- End Database Interaction ---

        # --- Session Management ---
        # Store user's google_id in Flask's session cookie to track login state
        session.clear() # Good practice to clear old session data
        session['google_id'] = user.google_id
        session.permanent = True # Make session last longer than browser close
        current_app.logger.info(f"User {email} added to session.")
        # --- End Session Management ---

        flash(f"Successfully logged in as {name or email}!", "success") # Show success message

    except Exception as e:
        # Catch any other unexpected errors during the process
        current_app.logger.error(f"Error in OAuth callback: {e}", exc_info=True) # Log full traceback
        flash("Authentication failed during callback.", "danger") # Show generic error to user

    # Always redirect back to the main page after attempting login
    return redirect(url_for('index')) # Assumes your main route function is named 'index'


@auth_bp.route('/logout')
def logout():
    """Logs the user out by clearing the session."""
    # Remove user identifier from session
    user_id = session.pop('google_id', None) # Safely remove key
    if user_id:
         current_app.logger.info(f"User with google_id {user_id} logged out.")
    else:
         current_app.logger.warning("Logout route hit but no user was in session.")

    flash("You have been logged out successfully.", "info")
    # Redirect back to the main page
    return redirect(url_for('index'))

# --- End of /var/www/postwmt/app/auth.py ---
