from ics import Calendar, Event
from datetime import datetime # Keep for type hinting if used
from dateutil import tz

# --- Imports for Google Calendar API ---
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials # For type hinting

# --- Flask Imports ---
from flask import current_app # For logging

# Define the IANA timezone name used by the parser
# This should match the value used in app/parser.py
# TODO: Consider making this a configuration variable
SCHEDULE_TZ_NAME = 'America/New_York'

# --- ICS Generation Function ---
def create_ics_content(parsed_events: list) -> str:
    """
    Creates iCalendar (.ics) file content from parsed events.

    Args:
        parsed_events: A list of event dictionaries from parse_schedule_text.
                       Each dict must have 'summary', 'start_dt', 'end_dt'.
                       start_dt and end_dt MUST be timezone-aware datetime objects.

    Returns:
        A string containing the calendar data in iCalendar format, or empty string on failure.
    """
    current_app.logger.info(f"Starting ICS content generation for {len(parsed_events)} events.")
    try:
        c = Calendar()
        for item in parsed_events:
            # Get data safely using .get() with defaults
            summary = item.get('summary', 'Work Shift')
            start_dt_aware = item.get('start_dt')
            end_dt_aware = item.get('end_dt')
            date_str = item.get('date_str', 'Unknown Date')

            # Ensure datetimes are valid and timezone-aware before adding
            if not start_dt_aware or not end_dt_aware:
                 current_app.logger.warning(f"Skipping ICS event due to missing start/end dt: {summary} on {date_str}")
                 continue
            if start_dt_aware.tzinfo is None or end_dt_aware.tzinfo is None:
                 current_app.logger.error(f"Received naive datetime for ICS event {summary} on {date_str}. Skipping.")
                 # Avoid trying to fix here; parser should provide aware times.
                 continue

            e = Event()
            e.name = summary
            e.begin = start_dt_aware # Use the timezone-aware datetime
            e.end = end_dt_aware     # Use the timezone-aware datetime
            # Optional: Add a unique ID to help calendar clients update/avoid duplicates
            # e.uid = f"{start_dt_aware.strftime('%Y%m%dT%H%M%S%z')}-{summary}@postwmt.gewnthar.dev"
            c.events.add(e)

        # Use serialize() for clarity, avoids FutureWarning from str(c)
        ics_string = c.serialize()
        current_app.logger.info(f"Finished ICS content generation, length: {len(ics_string)}")
        return ics_string

    except Exception as e:
        current_app.logger.error(f"Error during ICS generation: {e}", exc_info=True)
        return "" # Return empty string on error


# --- Google Calendar Event Insertion Function ---
def insert_event(creds: Credentials, event_details: dict) -> bool:
    """Inserts a single event into the primary Google Calendar."""
    # --- NEW DEBUG LINE ---
    current_app.logger.debug(f"--- insert_event function entered for date: {event_details.get('date_str', 'Unknown Date')} ---")
    # --- END NEW DEBUG LINE ---

    # --- Input Validation ---
    if not creds:
        current_app.logger.error("insert_event called with invalid credentials.")
        return False
    summary = event_details.get('summary')
    start_dt_aware = event_details.get('start_dt')
    end_dt_aware = event_details.get('end_dt')
    date_str = event_details.get('date_str', 'Unknown Date') # Re-get for logging clarity below
    if not all([summary, start_dt_aware, end_dt_aware]):
        current_app.logger.error(f"insert_event called with missing summary/start/end details for {date_str}")
        return False
    if not start_dt_aware.tzinfo or not end_dt_aware.tzinfo:
        # This check is crucial - ensures parser gave us timezone-aware datetimes
        current_app.logger.error(f"insert_event called with naive datetime for {summary} on {date_str}. Skipping.")
        return False
    # --- End Input Validation ---

    try:
        # This is now the most likely place for an issue if the first debug log appears but the second doesn't
        current_app.logger.debug(f"Attempting to build Google Calendar service object for {date_str}")
        service = build('calendar', 'v3', credentials=creds, static_discovery=False)
        current_app.logger.debug(f"Successfully built Google Calendar service object for {date_str}")

        # Construct the event body WITHOUT the timeZone key
        # Rely on the timezone offset included in the ISO format dateTime string
        event_body = {
            'summary': summary,
            'start': {
                'dateTime': start_dt_aware.isoformat(), # ISO format includes offset e.g., -04:00
                # 'timeZone': SCHEDULE_TZ_NAME, # REMAINS REMOVED
            },
            'end': {
                'dateTime': end_dt_aware.isoformat(), # ISO format includes offset
                # 'timeZone': SCHEDULE_TZ_NAME, # REMAINS REMOVED
           },
        }

        # --- EXISTING CRITICAL DEBUG LINE ---
        current_app.logger.debug(f"Event Body being sent from utils.py: {event_body}")
        # --- END EXISTING DEBUG LINE ---

        event = service.events().insert(calendarId='primary', body=event_body).execute()
        current_app.logger.info(f"Google Calendar Event created: {event.get('htmlLink')}")
        return True

    except HttpError as error:
         # Log the specific date that failed along with the error
        current_app.logger.error(f"Google API HttpError inserting event for {date_str}: {error}")
        # Log the problematic event body for detailed debugging
        current_app.logger.error(f"Failing event body for {date_str}: {event_body}") # This might fail if event_body wasn't created
        return False
    except Exception as e:
        # General exception logging
        current_app.logger.error(f"Unexpected error in insert_event for {date_str}: {e}", exc_info=True)
        # Also try to log the event body if possible, in case the error happened after it was defined
        try:
            current_app.logger.error(f"Event body at time of general error: {event_body}")
        except NameError:
             current_app.logger.error("Event body was not defined when general error occurred.")
        return False

