# /var/www/postwmt/app/routes.py
from flask import (render_template, request, Response, current_app, url_for, session, flash, redirect)
from .models import User, db # Import User model and db instance
from app import oauth # Import the oauth instance for Authlib operations

# --- Google API Imports ---
# Make sure these are installed: pip install google-api-python-client google-auth google-auth-oauthlib
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
import google.auth.transport.requests # Needed for credentials.refresh

# --- Local App Imports ---
try:
    # Assumes parser function is in app/parser.py
    from .parser import parse_schedule_text
except ImportError as e:
    # Log error and provide a dummy function if import fails,
    # so the app might still start for other routes.
    # Use print for startup issues as logger might not be ready
    print(f"ERROR: Failed to import parse_schedule_text: {e}")
    def parse_schedule_text(text):
        print("ERROR: parse_schedule_text dummy function called!")
        return []

try:
    # Assumes ics generator function is in app/utils.py
    from .utils import create_ics_content
except ImportError as e:
    print(f"ERROR: Failed to import create_ics_content: {e}")
    def create_ics_content(events):
        print("ERROR: create_ics_content dummy function called!")
        return ""

# --- Application Routes ---

@current_app.route('/')
def index():
    """Renders the main page, showing user info if logged in."""
    current_app.logger.debug("--- index route entered ---")
    user = None
    google_id = session.get('google_id')
    current_app.logger.debug(f"Session google_id: {google_id}")

    if google_id:
        try:
            user = User.query.filter_by(google_id=google_id).first()
            if user:
                 current_app.logger.debug(f"Found user in DB: {user.email}")
            else:
                 current_app.logger.warning(f"google_id {google_id} in session, but user not found in DB!")
                 session.pop('google_id', None) # Clear invalid session
        except Exception as e:
             current_app.logger.error(f"Error querying database for user: {e}", exc_info=True)
             session.pop('google_id', None)
             user = None

    # URLs needed for template forms/links
    try:
        # Make sure the endpoint names ('generate_ics', 'submit_to_google', 'auth.login', 'auth.logout')
        # correctly match how the routes/blueprints are defined and registered.
        generate_ics_url = url_for('generate_ics')
        submit_google_url = url_for('submit_to_google')
        login_url = url_for('auth.login')
        logout_url = url_for('auth.logout')
    except Exception as e:
         # Log error if URL generation fails
         current_app.logger.error(f"Error generating URLs for index template: {e}", exc_info=True)
         # Provide default/dummy URLs or handle error appropriately
         generate_ics_url = '#'
         submit_google_url = '#'
         login_url = '#'
         logout_url = '#'

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
    Handles form submission for posting events to Google Calendar.
    Requires user to be logged in via Google OAuth.
    """
    current_app.logger.info("--- /submit_to_google route entered ---")

    # --- Authentication Check ---
    google_id = session.get('google_id')
    if not google_id:
        flash("You must be logged in to post to Google Calendar.", "warning")
        return redirect(url_for('index'))

    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        flash("Logged in user not found in database. Please log in again.", "danger")
        session.pop('google_id', None)
        return redirect(url_for('index'))

    if not user.google_refresh_token:
        flash("Missing Google permission (refresh token) to access calendar offline. Please log in again, ensuring you grant calendar access.", "danger")
        return redirect(url_for('index'))
    # --- End Authentication Check ---

    schedule_text = request.form.get('schedule_text', '')
    if not schedule_text:
        flash("No schedule text was submitted.", "warning")
        return redirect(url_for('index'))

    current_app.logger.info(f"Received schedule text (length: {len(schedule_text)}) for Google Calendar submission.")

    # --- Parse Schedule ---
    try:
        parsed_events = parse_schedule_text(schedule_text)
        current_app.logger.info(f"Parser returned {len(parsed_events)} events for Google Calendar.")
    except Exception as e:
        current_app.logger.error(f"Error during parsing for Google Calendar: {e}", exc_info=True)
        flash("An error occurred while parsing the schedule.", "danger")
        return redirect(url_for('index'))

    if not parsed_events:
        flash("Could not parse any valid events from the text provided. Please check the format.", "warning")
        return redirect(url_for('index'))
    # --- End Parse Schedule ---

    # --- Google Calendar API Interaction ---
    success_count = 0
    fail_count = 0
    service = None # Initialize service to None
    try:
        # 1. Create Credentials object from stored refresh token
        credentials = Credentials(
            None, # No access token initially
            refresh_token=user.google_refresh_token,
            # Get token endpoint URL safely from Authlib's discovered metadata
            token_uri=oauth.google.server_metadata.get('token_endpoint'),
            client_id=current_app.config['GOOGLE_CLIENT_ID'],
            client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
            scopes=current_app.config['GOOGLE_SCOPES']
        )

        # 2. Refresh the access token
        try:
            # Use google.auth.transport.requests.Request for the refresh request transport
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            current_app.logger.info("Successfully refreshed Google access token.")
        except RefreshError as e:
            current_app.logger.error(f"Google refresh token failed: {e}. User may need to re-authenticate.")
            session.pop('google_id', None)
            # Consider deleting the bad refresh token from DB? Maybe not automatically.
            # user.google_refresh_token = None
            # db.session.commit()
            flash("Your Google authorization has expired or was revoked. Please log in again.", "danger")
            return redirect(url_for('index'))


        # 3. Build the Google Calendar service client
        # Use static_discovery=False for potentially more up-to-date API definitions
        service = build('calendar', 'v3', credentials=credentials, static_discovery=False)

        # 4. Insert events one by one
        for event_data in parsed_events:
            # Ensure datetimes have timezone info before formatting
            if not event_data['start_dt'].tzinfo or not event_data['end_dt'].tzinfo:
                 current_app.logger.warning(f"Skipping event for {event_data['date_str']} due to missing timezone info.")
                 fail_count += 1
                 continue

            event_resource = {
                'summary': event_data['summary'],
                'start': {
                    'dateTime': event_data['start_dt'].isoformat(), # ISO 8601 format includes offset
                    'timeZone': str(event_data['start_dt'].tzinfo), # Explicitly provide TZ identifier
                },
                'end': {
                    'dateTime': event_data['end_dt'].isoformat(),
                    'timeZone': str(event_data['end_dt'].tzinfo),
                },
                # 'description': f"Posted by PostWMT. Overtime: {event_data['is_overtime']}" # Optional
            }

            try:
                current_app.logger.debug(f"Attempting to insert event: {event_resource['summary']} on {event_data['date_str']}")
                created_event = service.events().insert(
                    calendarId='primary', # Use the user's primary calendar
                    body=event_resource
                ).execute()
                current_app.logger.info(f"Event created: {created_event.get('htmlLink')}")
                success_count += 1
            except HttpError as error:
                current_app.logger.error(f"An API error occurred inserting event for {event_data['date_str']}: {error}")
                fail_count += 1
            except Exception as e:
                # Catch other potential errors during the API call for a specific event
                current_app.logger.error(f"A non-API error occurred inserting event for {event_data['date_str']}: {e}", exc_info=True)
                fail_count += 1
        # --- End Google Calendar API Interaction ---

        # Flash result message based on counts
        if success_count > 0 and fail_count == 0:
            flash(f"Successfully posted {success_count} events to your Google Calendar!", "success")
        elif success_count > 0 and fail_count > 0:
            flash(f"Posted {success_count} events, but failed to post {fail_count} events. Check server logs for details.", "warning")
        else: # success_count == 0
             if fail_count > 0:
                 flash(f"Failed to post any events to Google Calendar ({fail_count} failures). Check server logs for details.", "danger")
             else:
                 # This case should ideally not happen if parsed_events was not empty,
                 # but handle it just in case.
                 flash("No events were posted. Parsing might have yielded empty results after filtering?", "warning")

    except Exception as e:
        # Catch unexpected errors in the main try block (e.g., credentials refresh issues handled above)
        current_app.logger.error(f"Unexpected error during Google Calendar submission: {e}", exc_info=True)
        flash("An unexpected error occurred while submitting to Google Calendar.", "danger")

    # Redirect back to the index page regardless of outcome
    return redirect(url_for('index'))


@current_app.route('/generate_ics', methods=['POST'])
def generate_ics():
    """
    Handles form submission, parses text, generates ICS,
    and returns it as a downloadable file. No login required.
    """
    # --- Keep the existing generate_ics function code here ---
    # (Including logging added previously)
    current_app.logger.warning("--- /generate_ics route entered ---")
    schedule_text = request.form.get('schedule_text', '')
    if not schedule_text:
        current_app.logger.error("Received empty schedule text for ICS generation.")
        return "Please paste schedule text.", 400
    current_app.logger.info(f"Received schedule text (length: {len(schedule_text)}) for ICS generation.")
    try:
        parsed_events = parse_schedule_text(schedule_text)
        current_app.logger.info(f"Parser returned {len(parsed_events)} events.")
    except Exception as e:
        current_app.logger.error(f"Error during parsing for ICS: {e}", exc_info=True)
        return "An error occurred while parsing the schedule.", 500
    if not parsed_events:
        current_app.logger.warning("Parser returned no valid events for ICS generation.")
        return "Could not parse any valid events from the text provided. Please check the format.", 400
    try:
        ics_content = create_ics_content(parsed_events)
        current_app.logger.info(f"Generated ICS content length: {len(ics_content)}")
    except Exception as e:
        current_app.logger.error(f"Error during ICS content creation: {e}", exc_info=True)
        return "An error occurred while generating the ICS file.", 500
    if not ics_content or len(ics_content) < 50:
         current_app.logger.error(f"create_ics_content returned unusually short/empty string! Length: {len(ics_content)}")
         return "Failed to generate valid ICS content.", 500
    current_app.logger.info("--- Sending ICS file response ---")
    return Response(
        ics_content,
        mimetype="text/calendar",
        headers={"Content-disposition":
                 "attachment; filename=schedule.ics"}
    )
# --- End of /var/www/postwmt/app/routes.py ---
