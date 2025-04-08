# /var/www/postwmt/app/utils.py
from ics import Calendar, Event
from datetime import datetime # Keep this import
import pytz # Import pytz if not using dateutil.tz directly

def create_ics_content(parsed_events: list) -> str:
    """
    Creates iCalendar (.ics) file content from parsed events.

    Args:
        parsed_events: A list of event dictionaries from parse_schedule_text.
                       Each dict must have 'summary', 'start_dt', 'end_dt'.
                       start_dt and end_dt MUST be timezone-aware datetime objects.

    Returns:
        A string containing the calendar data in iCalendar format.
    """
    c = Calendar()
    for item in parsed_events:
        # Ensure datetimes are timezone-aware before adding
        if item['start_dt'].tzinfo is None or item['end_dt'].tzinfo is None:
             print(f"Warning: Event '{item['summary']}' on {item['date_str']} lacks timezone info. Skipping.")
             continue # Skip events without timezone

        e = Event()
        e.name = item['summary']
        e.begin = item['start_dt'] # Use the timezone-aware datetime
        e.end = item['end_dt']     # Use the timezone-aware datetime
        # You could add more details here if needed (location, description etc.)
        c.events.add(e)

    # Return the calendar data as a string
    return str(c) # or c.serialize()
