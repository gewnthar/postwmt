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
try:
    from .parser import parse_schedule_text
    # Import the timezone name defined in parser/utils to keep it consistent
    from .utils import SCHEDULE_TZ_NAME
except ImportError as e:
    print(f"ERROR: Failed to import from parser/utils: {e}")
    # Define fallbacks if imports fail during startup
    def parse_schedule_text(text): print("ERROR: parser dummy called!"); return []
    SCHEDULE_TZ_NAME = 'America/New_York'

try:
    from .utils import create_ics_content, insert_event
except ImportError as e:
    print(f"ERROR: Failed to import utils functions: {e}")
    def create_ics_content(events): print("ERROR: ics dummy"); return ""
    def insert_event(c, e): print("ERROR: insert dummy"); return False

# --- Application Routes ---

@current_app.route('/')
def index():
    """Renders the main page, showing user info if logged in."""
    current_app.logger.debug("--- index route entered ---")
    user = None
    google_id = session.get('google_id')
    if google_id:
        try:
            user = User.query.filter_by(google_id=google_id).first()
            if not user: session.pop('google_id', None)
        except Exception as e:
             current_app.logger.error(f"Error querying DB for user: {e}", exc_info=True)
             session.pop('google_id', None); user = None
    try:
        # Generate URLs needed for the template
        generate_ics_url = url_for('generate_ics')
        submit_google_url = url_for('submit_to_google')
        login_url = url_for('auth.login')
        logout_url = url_for('auth.logout')
    except Exception as e:
         current_app.logger.error(f"Error generating URLs: {e}", exc_info=True)
         generate_ics_url, submit_google_url, login_url, logout_url = '#', '#', '#', '#'
    try:
        return render_template('index.html',
                               title='PostWMT Schedule Tool',
                               current_user=user,
                               generate_ics_url=generate_ics_url,
                               submit_google_url=submit_google_url,
                               login_url=login_url,
                               logout_url=logout_url)
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

    # --- Authentication Check ---
    google_id = session.get('google_id')
    if not google_id: flash("Login required.", "warning"); return redirect(url_for('index'))
    user = User.query.filter_by(google_id=google_id).first()
    if not user: flash("User not found.", "danger"); session.pop('google_id', None); return redirect(url_for('index'))
    if not user.google_refresh_token: flash("Missing refresh token.", "danger"); return redirect(url_for('index'))

    # --- Form Data and Parsing ---
    schedule_text = request.form.get('schedule_text', '')
    if not schedule_text: flash("No schedule text submitted.", "warning"); return redirect(url_for('index'))
    # MAX_SCHEDULE_TEXT_LENGTH check was removed in the user's provided code.
    # If this is desired, it should be re-added. For now, I'm using the exact code provided.
    # if len(schedule_text) > MAX_SCHEDULE_TEXT_LENGTH:
    #     flash(f"Schedule text is too long (max {MAX_SCHEDULE_TEXT_LENGTH // 1024}KB).", "warning")
    #     return redirect(url_for('index'))
    try:
        parsed_events = parse_schedule_text(schedule_text)
        current_app.logger.info(f"Parser returned {len(parsed_events)} events.")
    except Exception as e:
        current_app.logger.error(f"Error during parsing: {e}", exc_info=True); flash("Error parsing schedule.", "danger"); return redirect(url_for('index'))
    if not parsed_events:
        flash("Could not parse any valid events from text.", "warning"); return redirect(url_for('index'))

    # --- Google Calendar API Interaction ---
    success_count, fail_count, delete_count = 0, 0, 0
    try:
        # 1. Create and Refresh Credentials object
        credentials = Credentials(
            None, refresh_token=user.google_refresh_token,
            token_uri=oauth.google.server_metadata.get('token_endpoint'),
            client_id=current_app.config['GOOGLE_CLIENT_ID'],
            client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
            scopes=current_app.config['GOOGLE_SCOPES']
        )
        try:
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            current_app.logger.info("Successfully refreshed Google access token.")
        except RefreshError as e:
            current_app.logger.error(f"Google refresh token failed: {e}. Re-login required.")
            session.pop('google_id', None)
            flash("Google authorization expired. Please log in again.", "danger")
            return redirect(url_for('index'))

        # 2. Build the Calendar service object
        # This service object is used for listing/deleting events.
        # The insert_event utility will build its own service instance internally for insertion.
        service = build('calendar', 'v3', credentials=credentials, static_discovery=False)

        # 3. Determine Date Range and Delete Old Events
        min_dt = min(e['start_dt'] for e in parsed_events)
        max_dt = max(e['end_dt'] for e in parsed_events)

        # Ensure SCHEDULE_TZ is obtained correctly
        # It's imported from .utils, which should define it based on SCHEDULE_TZ_NAME
        # If SCHEDULE_TZ_NAME is directly from .utils, it will be used.
        # Otherwise, ensure SCHEDULE_TZ is available.
        # For this code, SCHEDULE_TZ_NAME is imported, so tz.gettz(SCHEDULE_TZ_NAME) is appropriate.
        schedule_timezone = tz.gettz(SCHEDULE_TZ_NAME)
        if not schedule_timezone:
            current_app.logger.error(f"Could not get timezone for {SCHEDULE_TZ_NAME}. Falling back to UTC for range deletion.")
            schedule_timezone = tz.tzutc() # Fallback, though parser should use a valid one.

        time_min_dt = datetime.combine(min_dt.date(), time.min).replace(tzinfo=schedule_timezone)
        time_max_dt = datetime.combine(max_dt.date() + timedelta(days=1), time.min).replace(tzinfo=schedule_timezone)
        time_min_iso, time_max_iso = time_min_dt.isoformat(), time_max_dt.isoformat()

        current_app.logger.info(f"Checking for existing #postwmt events between {time_min_iso} and {time_max_iso}")
        page_token = None
        while True:
            existing_events_result = service.events().list(
                calendarId='primary', timeMin=time_min_iso, timeMax=time_max_iso,
                q='#postwmt', singleEvents=True, pageToken=page_token).execute()
            for old_event in existing_events_result.get('items', []):
                try:
                    service.events().delete(calendarId='primary', eventId=old_event['id']).execute()
                    delete_count += 1
                    current_app.logger.info(f"Deleted old event: {old_event.get('summary')} ({old_event['id']})")
                except HttpError as http_err:
                    current_app.logger.error(f"HttpError deleting event {old_event['id']}: {http_err}")
                    # Optionally, count this as a failure or handle differently
                except Exception as ex:
                    current_app.logger.error(f"Exception deleting event {old_event['id']}: {ex}", exc_info=True)

            page_token = existing_events_result.get('nextPageToken')
            if not page_token: break
        current_app.logger.info(f"Deleted {delete_count} old #postwmt events in the date range.")

        # 4. Loop through parsed events and call the insert_event utility function
        # The 'credentials' object is passed, as 'insert_event' expects it.
        for event_data in parsed_events:
            # Add a hashtag to the summary for future deletion/identification
            event_data['summary'] = f"#postwmt {event_data.get('summary', 'Work Shift')}"
            if insert_event(credentials, event_data): # insert_event is from .utils
                success_count += 1
            else:
                fail_count += 1

        # 5. Flash Final Summary Message
        if success_count > 0 and fail_count == 0:
            flash(f"Successfully processed schedule: {success_count} events posted (removed {delete_count} previous).", "success")
        elif success_count > 0:
            flash(f"Partial success: Posted {success_count}, failed {fail_count} events (removed {delete_count} previous). Check logs.", "warning")
        elif fail_count > 0:
             flash(f"Failed to post any events ({fail_count} failures, removed {delete_count} previous). Check logs.", "danger")
        elif delete_count > 0: # Only deletions, no new events
             flash(f"Removed {delete_count} previous #postwmt events. No new events were added from this submission.", "info")
        else: # No successes, no failures (implies parsed_events was empty or filtered out), no deletions
             flash("No new events were posted from this submission, and no previous #postwmt events were found in the range to remove.", "info")


    except HttpError as http_err_outer:
        # Handle HttpErrors that occur outside the delete/insert loops (e.g., service.events().list())
        current_app.logger.error(f"Outer HttpError during Google Calendar submission: {http_err_outer}", exc_info=True)
        flash(f"A Google API error occurred: {http_err_outer.resp.status} {http_err_outer._get_reason()}. Check logs.", "danger")
    except Exception as e:
        current_app.logger.error(f"Unexpected error during Google Calendar submission: {e}", exc_info=True)
        flash("An unexpected error occurred while submitting to Google Calendar.", "danger")

    return redirect(url_for('index'))


@current_app.route('/generate_ics', methods=['POST'])
def generate_ics():
    """ Handles ICS generation. """
    # This code remains unchanged and seems correct.
    current_app.logger.warning("--- /generate_ics route entered ---")
    schedule_text = request.form.get('schedule_text', '')
    if not schedule_text: return "Please paste schedule text.", 400
    # MAX_SCHEDULE_TEXT_LENGTH check was removed in the user's provided code.
    # if len(schedule_text) > MAX_SCHEDULE_TEXT_LENGTH:
    #     current_app.logger.error(f"Schedule text too long for ICS generation: {len(schedule_text)} bytes.")
    #     return f"Schedule text is too long (max {MAX_SCHEDULE_TEXT_LENGTH // 1024}KB).", 400
    try:
        parsed_events = parse_schedule_text(schedule_text)
    except Exception as e:
        current_app.logger.error(f"Error parsing for ICS: {e}", exc_info=True)
        return "An error occurred while parsing the schedule.", 500
    if not parsed_events:
        return "Could not parse any valid events from the text provided. Please check the format.", 400

    # Add #postwmt to summary for ICS files as well for consistency, if desired
    # for event_data in parsed_events:
    #    event_data['summary'] = f"#postwmt {event_data.get('summary', 'Work Shift')}"

    ics_content = create_ics_content(parsed_events)
    if not ics_content or len(ics_content) < 50: # Basic check for valid ICS
        current_app.logger.error(f"create_ics_content returned unusually short/empty string! Length: {len(ics_content)}")
        return "Failed to generate valid ICS content.", 500

    return Response(ics_content, mimetype="text/calendar",
                    headers={"Content-disposition": "attachment; filename=schedule.ics"})
# --- End of /var/www/postwmt/app/routes.py ---
