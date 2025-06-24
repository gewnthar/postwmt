# /var/www/postwmt/app/routes.py
from flask import (render_template, request, Response, current_app, url_for,
                   session, flash, redirect)
from .models import User, db
from app import oauth

# --- Google API Imports ---
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
import google.auth.transport.requests

# --- Datetime Imports ---
from datetime import datetime, time, timedelta
from dateutil import tz

# --- Local App Imports ---
# These try/except blocks are for resilience during development
try:
    from .parser import parse_schedule_text
except ImportError as e:
    print(f"ERROR: Failed to import parse_schedule_text: {e}")
    def parse_schedule_text(text): return []

try:
    from .utils import create_ics_content, insert_event, SCHEDULE_TZ_NAME
except ImportError as e:
    print(f"ERROR: Failed to import from utils: {e}")
    def create_ics_content(events): return ""
    def insert_event(c, e): return False
    SCHEDULE_TZ_NAME = 'America/New_York' # Fallback

# --- Application Routes ---

@current_app.route('/')
def index():
    """Renders the main page, showing user info if logged in."""
    user = None
    if google_id := session.get('google_id'):
        try:
            user = User.query.filter_by(google_id=google_id).first()
            if not user:
                 session.pop('google_id', None)
        except Exception as e:
             current_app.logger.error(f"Error querying DB for user: {e}", exc_info=True)
             session.pop('google_id', None)
             user = None
    try:
        return render_template('index.html',
                               title='PostWMT Schedule Tool',
                               current_user=user,
                               generate_ics_url=url_for('generate_ics'),
                               submit_google_url=url_for('submit_to_google'),
                               login_url=url_for('auth.login'),
                               logout_url=url_for('auth.logout'))
    except Exception as e:
        current_app.logger.error(f"Error rendering index.html: {e}", exc_info=True)
        return "Error loading page template.", 500


@current_app.route('/submit_to_google', methods=['POST'])
def submit_to_google():
    """
    Handles schedule submission: Finds date range, deletes old #postwmt events
    in that range, then inserts new events by calling the insert_event utility.
    """
    current_app.logger.info("--- /submit_to_google route entered ---")

    # 1. Authentication and Form Data Checks
    if not (google_id := session.get('google_id')):
        flash("Login required to submit to Google Calendar.", "warning")
        return redirect(url_for('index'))
    user = User.query.filter_by(google_id=google_id).first()
    if not user or not user.google_refresh_token:
        flash("Valid authorization with refresh token required. Please log in again.", "danger")
        if user: session.pop('google_id', None)
        return redirect(url_for('index'))
    if not (schedule_text := request.form.get('schedule_text')):
        flash("No schedule text submitted.", "warning")
        return redirect(url_for('index'))

    # 2. Parse Schedule Text
    try:
        parsed_events = parse_schedule_text(schedule_text)
        current_app.logger.info(f"Parser returned {len(parsed_events)} events.")
    except Exception as e:
        current_app.logger.error(f"Error during parsing: {e}", exc_info=True)
        flash("An error occurred while parsing the schedule.", "danger")
        return redirect(url_for('index'))
    if not parsed_events:
        flash("Could not parse any valid events from the provided text.", "warning")
        return redirect(url_for('index'))

    # 3. Google Calendar API Interaction
    success_count, fail_count, delete_count = 0, 0, 0
    try:
        # Create and refresh credentials
        credentials = Credentials(
            None, refresh_token=user.google_refresh_token,
            token_uri=oauth.google.server_metadata.get('token_endpoint'),
            client_id=current_app.config['GOOGLE_CLIENT_ID'],
            client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
            scopes=current_app.config['GOOGLE_SCOPES']
        )
        credentials.refresh(google.auth.transport.requests.Request())
        current_app.logger.info("Successfully refreshed Google access token.")

        service = build('calendar', 'v3', credentials=credentials, static_discovery=False)

        # Determine Date Range and Delete Old Events
        min_dt = min(e['start_dt'] for e in parsed_events)
        max_dt = max(e['end_dt'] for e in parsed_events)
        schedule_tz = tz.gettz(SCHEDULE_TZ_NAME)
        time_min = datetime.combine(min_dt.date(), time.min).replace(tzinfo=schedule_tz).isoformat()
        time_max = datetime.combine(max_dt.date() + timedelta(days=1), time.min).replace(tzinfo=schedule_tz).isoformat()

        page_token = None
        while True:
            existing = service.events().list(
                calendarId='primary', timeMin=time_min, timeMax=time_max,
                q='#postwmt', singleEvents=True, pageToken=page_token).execute()
            for old_event in existing.get('items', []):
                service.events().delete(calendarId='primary', eventId=old_event['id']).execute()
                delete_count += 1
            page_token = existing.get('nextPageToken')
            if not page_token: break
        current_app.logger.info(f"Deleted {delete_count} old #postwmt events.")

        # Insert New Events by calling the utility function
        for event_data in parsed_events:
            if insert_event(credentials, event_data):
                success_count += 1
            else:
                fail_count += 1

        # Flash the final summary message
        if success_count > 0 and fail_count == 0:
            flash(f"Successfully processed schedule: {success_count} events posted (removed {delete_count} previous).", "success")
        elif success_count > 0:
            flash(f"Partial success: Posted {success_count}, failed {fail_count} events (removed {delete_count} previous). Check logs.", "warning")
        else: # Only failures or only deletions
            flash(f"Failed to post any new events ({fail_count} failures, removed {delete_count} previous). Check logs.", "danger")

    except RefreshError as e:
        current_app.logger.error(f"Google refresh token failed: {e}. Logging out user.")
        session.pop('google_id', None)
        flash("Your Google authorization has expired or was revoked. Please log in again.", "danger")
    except Exception as e:
        current_app.logger.error(f"Unexpected error during Google Calendar submission: {e}", exc_info=True)
        flash("An unexpected error occurred while submitting to Google Calendar.", "danger")

    return redirect(url_for('index'))


@current_app.route('/generate_ics', methods=['POST'])
def generate_ics():
    """ Handles ICS generation. """
    # This code remains unchanged and should be working correctly.
    schedule_text = request.form.get('schedule_text', '')
    if not schedule_text: return "Please paste schedule text.", 400
    try:
        parsed_events = parse_schedule_text(schedule_text)
    except Exception as e:
        current_app.logger.error(f"Error parsing for ICS: {e}", exc_info=True)
        return "An error occurred while parsing the schedule.", 500
    if not parsed_events:
        return "Could not parse any valid events from the text provided. Please check the format.", 400
    ics_content = create_ics_content(parsed_events)
    if not ics_content:
        return "Failed to generate valid ICS content.", 500
    return Response(ics_content, mimetype="text/calendar",
                    headers={"Content-disposition": "attachment; filename=schedule.ics"})


@current_app.route('/privacy')
def privacy_policy():
    """Renders the privacy policy page."""
    try:
        return render_template('privacy.html', title='Privacy Policy - PostWMT')
    except Exception as e:
        current_app.logger.error(f"Error rendering privacy.html: {e}", exc_info=True)
        return "Error loading privacy policy page.", 500

# --- End of /var/www/postwmt/app/routes.py ---