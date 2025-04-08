# /var/www/postwmt/app/parser.py
import re
import datetime
from dateutil import tz # Or use pytz if preferred, ensure installed
from flask import current_app # Import current_app for logging

def parse_schedule_text(text_schedule: str) -> list:
    """
    Parses raw schedule text into a list of events, trying to handle
    indicators possibly followed by other text on the same line.

    Args:
        text_schedule: The multi-line string containing the schedule.

    Returns:
        A list of dictionaries representing 8-hour work blocks.
    """
    current_app.logger.info("--- Starting schedule parsing ---")
    # Regex to find dates like MM/DD/YYYY anywhere on a line
    date_pattern = re.compile(r"(\d{2}/\d{2}/\d{4})")
    # Regex to find X or Digits (optional $) ONLY at the START of a line
    # Allows other text after the indicator.
    # Group 1: Digits (start hour) OR None if 'X' matched
    # Group 2: '$' (overtime marker) OR None
    # Group 3: 'X' (day off marker) OR None
    indicator_pattern = re.compile(r"^\s*(\d{1,2})(\$?)|^\s*(X)\s*")

    lines = text_schedule.strip().split('\n')

    parsed_events = []
    current_date_str = None
    # Get timezone from config or default (ensure pytz or dateutil is used consistently)
    # Using dateutil.tz here based on previous code
    SCHEDULE_TZ_NAME = 'America/New_York' # Make this configurable if needed
    SCHEDULE_TZ = tz.gettz(SCHEDULE_TZ_NAME)
    if not SCHEDULE_TZ:
        current_app.logger.error(f"Could not get timezone: {SCHEDULE_TZ_NAME}. Falling back to local.")
        SCHEDULE_TZ = tz.tzlocal()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1 # Move to next line index

        if not line:
            continue # Skip empty lines

        date_match = date_pattern.search(line)

        if date_match:
            # Found a potential date line, store it and look at the *next* line(s)
            current_date_str = date_match.group(1)
            current_app.logger.debug(f"Parser found date: {current_date_str}")

            # Look for the indicator on the immediately following non-empty lines
            indicator_found = False
            while i < len(lines):
                indicator_line = lines[i].strip()
                i += 1 # Consume this line too
                if not indicator_line: # Skip blank lines between date and indicator
                    continue

                indicator_match = indicator_pattern.match(indicator_line)
                if indicator_match:
                    indicator_found = True
                    start_hour_str = indicator_match.group(1)
                    is_overtime = (indicator_match.group(2) == '$')
                    is_day_off = (indicator_match.group(3) == 'X')

                    current_app.logger.debug(f"Parser found indicator line: '{indicator_line}' for date {current_date_str}")

                    if is_day_off:
                        current_app.logger.info(f"Day off detected for {current_date_str}")
                        # Reset date and break inner loop (we found the indicator for this date)
                        current_date_str = None
                        break

                    if start_hour_str:
                        try:
                            start_hour = int(start_hour_str)
                            if not (0 <= start_hour <= 23):
                                raise ValueError("Hour outside 0-23 range")

                            naive_start_dt = datetime.datetime.strptime(
                                f"{current_date_str} {start_hour:02d}:00",
                                "%m/%d/%Y %H:%M"
                            )
                            aware_start_dt = naive_start_dt.replace(tzinfo=SCHEDULE_TZ)
                            aware_end_dt = aware_start_dt + datetime.timedelta(hours=8)
                            summary = "Work Shift" + (" (OT)" if is_overtime else "")

                            parsed_events.append({
                                "date_str": current_date_str,
                                "start_dt": aware_start_dt,
                                "end_dt": aware_end_dt,
                                "is_overtime": is_overtime,
                                "summary": summary
                            })
                            current_app.logger.info(f"Added event for {current_date_str} at {start_hour_str}{'$' if is_overtime else ''}")

                        except ValueError as e:
                            current_app.logger.error(f"Failed to parse hour '{start_hour_str}' for date {current_date_str}: {e}")
                    else:
                         # Should not happen if X wasn't matched, but good to log
                         current_app.logger.warning(f"Indicator matched but no hour or X found for {current_date_str} on line '{indicator_line}'")

                    # Reset date, we've processed this entry. Break inner loop.
                    current_date_str = None
                    break # Exit the inner while loop looking for indicator
                else:
                    # This line wasn't blank and wasn't an indicator, maybe it's the next date?
                    # Check if it contains a date itself
                    next_date_match = date_pattern.search(indicator_line)
                    if next_date_match:
                        # It looks like the next date, push the index back and break inner loop
                        # so the outer loop can process it as a date line.
                        i -= 1 # Decrement index to reprocess this line in outer loop
                        current_app.logger.debug("Indicator not found, next line might be a date. Breaking inner loop.")
                        current_date_str = None # Discard current date as no indicator was found following it
                        break
                    else:
                        # It's some other text (like Day Name maybe), just ignore and keep looking
                        # for indicator on next line
                        current_app.logger.debug(f"Ignoring non-indicator/non-date line: '{indicator_line}'")
                        continue # Continue inner loop
            # End of inner while loop (looking for indicator)
            if not indicator_found and current_date_str:
                 current_app.logger.warning(f"Found date {current_date_str} but no subsequent indicator line found.")
                 current_date_str = None # Reset if no indicator found

        # else: Line didn't contain a date, ignore it unless we implement different logic

    current_app.logger.info(f"--- Finished parsing, found {len(parsed_events)} events ---")
    return parsed_events
