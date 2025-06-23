# /var/www/postwmt/app/parser.py
import re
import datetime
from dateutil import tz # Using dateutil for timezone handling
from flask import current_app # Import current_app for logging within Flask context

def parse_schedule_text(text_schedule: str) -> list:
    """
    Parses raw schedule text into a list of events, handling
    8-hour shifts, 10-hour shifts (marked with 'TEN'),
    overtime (marked with '$'), and days off ('X').

    Args:
        text_schedule: The multi-line string containing the schedule.

    Returns:
        A list of dictionaries representing work blocks. Each dict includes:
        date_str, start_dt (aware), end_dt (aware), is_overtime, summary.
    """
    current_app.logger.info("--- Starting schedule parsing (v2: TEN hour support) ---")
    # Regex to find dates like MM/DD/YYYY anywhere on a line
    date_pattern = re.compile(r"(\d{2}/\d{2}/\d{4})")
    # Updated Regex to find indicator at the start of a line (ignoring leading whitespace):
    # Group 1: Hour digits (e.g., "21")
    # Group 2: Optional literal "TEN"
    # Group 3: Optional literal "$"
    # OR
    # Group 4: Literal "X"
    # Allows other text (like Day Name) after the indicator components.
    indicator_pattern = re.compile(r"^\s*(\d{1,2})(TEN)?(\$)?|^\s*(X)\s*")

    lines = text_schedule.strip().split('\n')

    parsed_events = []
    current_date_str = None
    # Define timezone (Warrenton, VA is US/Eastern)
    # Consider making this configurable later if needed
    SCHEDULE_TZ_NAME = 'America/New_York'
    try:
        SCHEDULE_TZ = tz.gettz(SCHEDULE_TZ_NAME)
        if not SCHEDULE_TZ: # gettz returns None if invalid
             raise ValueError(f"Timezone '{SCHEDULE_TZ_NAME}' not found by dateutil.")
    except Exception as e:
        current_app.logger.error(f"Timezone Error: {e}. Falling back to server local time.")
        SCHEDULE_TZ = tz.tzlocal() # Fallback to server's local timezone

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1 # Move to next line index immediately after getting current

        if not line:
            continue # Skip empty lines

        date_match = date_pattern.search(line)

        # --- Found a Line Containing a Date ---
        if date_match:
            current_date_str = date_match.group(1)
            current_app.logger.debug(f"Parser found date: {current_date_str}")

            # Look ahead for the indicator on the NEXT non-empty line(s)
            indicator_found = False
            while i < len(lines): # Inner loop starting from the line *after* the date line
                indicator_line = lines[i].strip()
                i += 1 # Consume this potential indicator line index

                if not indicator_line:
                    continue # Skip blank lines between date and indicator

                # Try to match indicator pattern at the start of this line
                indicator_match = indicator_pattern.match(indicator_line)
                if indicator_match:
                    # Found the indicator line for the current date!
                    indicator_found = True
                    start_hour_str = indicator_match.group(1) # Will be digits or None
                    is_ten_hour = (indicator_match.group(2) == 'TEN') # Check if 'TEN' was captured
                    is_overtime = (indicator_match.group(3) == '$')   # Check if '$' was captured
                    is_day_off = (indicator_match.group(4) == 'X')    # Check if 'X' was captured

                    current_app.logger.debug(f"Parser found indicator line: '{indicator_line}' for date {current_date_str}")

                    if is_day_off:
                        # Handle Day Off
                        current_app.logger.info(f"Day off detected for {current_date_str}")
                        # Reset date, break inner loop (we found the 'X' for this date)
                        current_date_str = None
                        break # Exit inner loop

                    if start_hour_str:
                        # Handle Work Shift
                        try:
                            start_hour = int(start_hour_str)
                            if not (0 <= start_hour <= 23):
                                raise ValueError("Hour outside 0-23 range")

                            # Determine Duration based on 'TEN' flag
                            duration_hours = 10 if is_ten_hour else 8

                            # Create timezone-aware start datetime
                            naive_start_dt = datetime.datetime.strptime(
                                f"{current_date_str} {start_hour:02d}:00", "%m/%d/%Y %H:%M"
                            )
                            aware_start_dt = naive_start_dt.replace(tzinfo=SCHEDULE_TZ)

                            # Calculate end datetime using determined duration
                            aware_end_dt = aware_start_dt + datetime.timedelta(hours=duration_hours)

                            # Create summary string
                            summary = f"Work Shift ({duration_hours}hr)"
                            if is_overtime:
                                summary += " (OT)"

                            # Add event details to our results list
                            parsed_events.append({
                                "date_str": current_date_str,
                                "start_dt": aware_start_dt,
                                "end_dt": aware_end_dt,
                                "is_overtime": is_overtime,
                                "summary": summary
                            })
                            log_indicator = f"{start_hour_str}{'TEN' if is_ten_hour else ''}{'$' if is_overtime else ''}"
                            current_app.logger.info(f"Added event for {current_date_str} ({duration_hours}hr) indicator: {log_indicator}")

                        except ValueError as e:
                            current_app.logger.error(f"Failed to parse hour '{start_hour_str}' for date {current_date_str}: {e}")
                        except Exception as e_dt:
                             current_app.logger.error(f"Failed create datetime for {current_date_str} H:{start_hour_str}: {e_dt}", exc_info=True)
                    else:
                         # This case should ideally not happen if X wasn't matched, log warning
                         current_app.logger.warning(f"Indicator matched but no hour or X found for {current_date_str} on line '{indicator_line}'")

                    # We processed the indicator for this date, reset date and break inner loop
                    current_date_str = None
                    break # Exit the inner while loop (indicator handled)
                else:
                    # This line after the date wasn't blank and wasn't a valid indicator.
                    # Check if it looks like the *next* date entry.
                    next_date_match = date_pattern.search(indicator_line)
                    if next_date_match:
                        # Looks like the next date - push index back so outer loop processes it.
                        i -= 1
                        current_app.logger.debug(f"Indicator not found for {current_date_str}, assuming next line '{indicator_line}' is a date. Breaking inner loop.")
                        current_date_str = None # Discard current date as no indicator was found for it
                        break # Exit inner loop
                    else:
                        # It's some other text (like maybe a Day Name that was on its own line). Ignore it.
                        current_app.logger.debug(f"Ignoring non-indicator/non-date line '{indicator_line}' while searching for indicator for {current_date_str}")
                        continue # Continue inner loop to check the *next* line for the indicator
            # End of inner while loop (looking for indicator)

            # If we exit the inner loop and didn't find an indicator for the date we found...
            if not indicator_found and current_date_str:
                 current_app.logger.warning(f"Found date {current_date_str} but no subsequent indicator line found before next date or end of input.")
                 current_date_str = None # Reset date since it had no valid data

        # else: Line didn't contain a date, ignore it (could be Day Name etc.)

    current_app.logger.info(f"--- Finished parsing, found {len(parsed_events)} events ---")
    return parsed_events

# --- End of /var/www/postwmt/app/parser.py ---
