# /var/www/postwmt/app/routes.py
from flask import (render_template, request, Response, current_app, url_for,
                   session, flash, redirect)
from .models import User, db
from app import oauth
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
import google.auth.transport.requests
from datetime import datetime, time, timedelta
from dateutil import tz

# --- Local App Imports ---
from .parser import parse_schedule_text
from .utils import create_ics_content, insert_event, delete_events_in_range, SCHEDULE_TZ_NAME

# --- Application Routes ---

@current_app.route('/')
def index():
    """Renders the main page, checking for a logged-in user."""
    user = User.query.filter_by(google_id=session.get('google_id')).first() if 'google_id' in session else None
    return render_template('index.html', title='PostWMT Schedule Tool', current_user=user)

@current_app.route('/privacy')
def privacy_policy():
    """Renders the privacy policy page."""
    return render_template('privacy.html', title='Privacy Policy')

@current_app.route('/generate_ics', methods=['POST'])
def generate_ics():
    """Handles parsing text and returning an ICS file."""
    schedule_text = request.form.get('schedule_text', '')
    if not schedule_text:
        return "Please paste schedule text.", 400
    parsed_events = parse_schedule_text(schedule_text)
    if not parsed_events:
        return "Could not parse any valid events from the text provided.", 400
    ics_content = create_ics_content(parsed_events)
    if not ics_content:
        return "Failed to generate valid ICS content.", 500
    return Response(
        ics_content,
        mimetype="text/calendar",
        headers={"Content-disposition": "attachment; filename=schedule.ics"}
    )

@current_app.route('/submit_to_google', methods=['POST'])
def submit_to_google():
    """Handles the full suite of parsing, deleting old events, and inserting new events."""
    if 'google_id' not in session:
        flash("You must be logged in to use this feature.", "warning")
        return redirect(url_for('index'))
    user = User.query.filter_by(google_id=session['google_id']).first()
    if not user or not user.google_refresh_token:
        flash("Your authorization is missing or has expired. Please log in again.", "danger")
        return redirect(url_for('auth.logout'))

    schedule_text = request.form.get('schedule_text', '')
    if not schedule_text:
        flash("No schedule text submitted.", "warning")
        return redirect(url_for('index'))

    parsed_events = parse_schedule_text(schedule_text)
    if not parsed_events:
        flash("Could not parse any valid events from the provided text. No changes made to calendar.", "warning")
        return redirect(url_for('index'))

    try:
        credentials = Credentials(
            None,
            refresh_token=user.google_refresh_token,
            token_uri=oauth.google.server_metadata.get('token_endpoint'),
            client_id=current_app.config['GOOGLE_CLIENT_ID'],
            client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
            scopes=current_app.config['GOOGLE_SCOPES']
        )
        credentials.refresh(google.auth.transport.requests.Request())
        current_app.logger.info("Successfully refreshed Google access token.")

        delete_count = delete_events_in_range(credentials, parsed_events)

        success_count, fail_count = 0, 0
        for event in parsed_events:
            if insert_event(credentials, event):
                success_count += 1
            else:
                fail_count += 1

        if success_count > 0 and fail_count == 0:
            flash(f"Successfully processed schedule: {success_count} events posted (removed {delete_count} previous).", "success")
        elif success_count > 0:
            flash(f"Partial success: Posted {success_count}, failed {fail_count} (removed {delete_count}).", "warning")
        else:
            flash(f"Failed to post any new events ({fail_count} failures, removed {delete_count}). Check logs.", "danger")

    except RefreshError as e:
        current_app.logger.error(f"Google refresh token failed: {e}. Logging out.")
        flash("Your Google authorization has expired. Please log in again.", "danger")
        return redirect(url_for('auth.logout'))
    except Exception as e:
        current_app.logger.error(f"Unexpected error during submission: {e}", exc_info=True)
        flash("An unexpected error occurred while submitting to Google Calendar.", "danger")

    return redirect(url_for('index'))