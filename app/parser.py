# /var/www/postwmt/app/parser.py
import re
import datetime
from dateutil import tz # Using dateutil for timezone handling
from flask import current_app # Import current_app for logging within Flask context

def parse_schedule_text(text_schedule: str) -> list:
    """
    Parses raw schedule text into a list of events, handling:
    - 8/10-hour shifts (TEN marker)
    - Overtime ($ marker on normal/TEN shifts)
    - RDO (X - skipped)
    - Annual Leave (A<HH> - creates 8hr event 'Annual Leave' starting at HH)
    - At-Or-After OT (AOA<HH> - creates 8hr shift + 2hr OT event after)
    - At-Or-Before OT (AOB<HH> - creates 2hr OT event before + 8hr shift)

    Args:
        text_schedule: The multi-line string containing the schedule.

    Returns:
        A list of dictionaries representing events. Each dict includes:
        date_str, start_dt (aware), end_dt (aware), is_overtime, summary.
    """
    current_app.logger.info("--- Starting schedule parsing (v4: AOA/AOB support) ---")
    # Regex to find dates like MM/DD/YYYY anywhere on a line
    date_pattern = re.compile(r"(\d{2}/\d{2}/\d{4})")

    # Final Regex to find indicator at start of line:
    # Option 1 (Work Shift): Group 1(hour), Group 2(TEN), Group 3($)
    # Option 2 (RDO): Group 4(X)
    # Option 3 (Annual Leave): Group 5(A<HH>), Group 6(HH digits only)
    # Option 4 (AOA): Group 7(AOA<HH>), Group 8(HH digits only)
    # Option 5 (AOB): Group 9(AOB<HH>), Group 10(HH digits only)
    indicator_pattern = re.compile(r"^\s*(?:(\d{1,2})(TEN)?(\$)?|(X)|(A<(\d{1,2})>)|(AOA<(\d{1,2})>)|(AOB<(\d{1,2})>))\s*")

    lines = text_schedule.strip().split('\n')

    parsed_events = []
    current_date_str = None
    # Define timezone (Should match what's needed for Google API/user)
    SCHEDULE_TZ_NAME = 'America/New_York'
    try:
        SCHEDULE_TZ = tz.gettz(SCHEDULE_TZ_NAME)
        if not SCHEDULE_TZ: raise ValueError(f"Timezone '{SCHEDULE_TZ_NAME}' not found.")
    except Exception as e:
        current_app.logger.error(f"Timezone Error: {e}. Falling back to server local time.")
        SCHEDULE_TZ = tz.tzlocal()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1 # Move index forward

        if not line: continue

        date_match = date_pattern.search(line)

        if date_match:
            # --- Found a Date ---
            current_date_str = date_match.group(1)
            current_app.logger.debug(f"Parser found date: {current_date_str}")

            indicator_found = False
            # Look ahead for the indicator on the NEXT non-empty line(s)
            while i < len(lines): # Inner loop for indicator
                indicator_line = lines[i].strip()
                i += 1 # Consume this line index

                if not indicator_line: continue # Skip blanks

                indicator_match = indicator_pattern.match(indicator_line)
                if indicator_match:
                    # --- Found a Valid Indicator ---
                    indicator_found = True
                    current_app.logger.debug(f"Parser found indicator line: '{indicator_line}' for date {current_date_str}")

                    # Determine which type matched using capture groups
                    start_hour_str = indicator_match.group(1) # Work shift hour
                    is_ten_hour_shift = (indicator_match.group(2) == 'TEN') # Work shift TEN flag
                    is_overtime_marker_shift = (indicator_match.group(3) == '$')   # Work shift OT flag
                    is_rdo = (indicator_match.group(4) == 'X')        # RDO ('X') flag
                    is_annual_leave = bool(indicator_match.group(5))  # Annual Leave ('A<HH>') flag
                    is_aoa = bool(indicator_match.group(7)) # AOA<HH> flag
                    is_aob = bool(indicator_match.group(9)) # AOB<HH> flag

                    # Process based on which indicator type was found
                    try:
                        if is_rdo:
                            # --- Handle Regular Day Off (X) ---
                            current_app.logger.info(f"RDO (X) detected for {current_date_str}. Skipping event.")

                        elif is_annual_leave:
                            # --- Handle Annual Leave (A<HH>) ---
                            annual_leave_hour_str = indicator_match.group(6) # Get HH digits
                            annual_leave_hour = int(annual_leave_hour_str)
                            if not (0 <= annual_leave_hour <= 23): raise ValueError("Annual Leave hour outside 0-23 range")

                            summary = "Annual Leave"
                            duration_hours = 8 # 8-hour block as requested

                            naive_start_dt = datetime.datetime.strptime(f"{current_date_str} {annual_leave_hour:02d}:00", "%m/%d/%Y %H:%M")
                            aware_start_dt = naive_start_dt.replace(tzinfo=SCHEDULE_TZ)
                            aware_end_dt = aware_start_dt + datetime.timedelta(hours=duration_hours)

                            parsed_events.append({
                                "date_str": current_date_str, "start_dt": aware_start_dt, "end_dt": aware_end_dt,
                                "is_overtime": False, "summary": summary })
                            current_app.logger.info(f"Added Annual Leave event for {current_date_str} starting {annual_leave_hour}:00 ({duration_hours}hr).")

                        elif is_aoa:
                            # --- Handle At-Or-After (AOA<HH>) ---
                            aoa_start_hour_str = indicator_match.group(8)
                            aoa_start_hour = int(aoa_start_hour_str)
                            if not (0 <= aoa_start_hour <= 23): raise ValueError("AOA hour outside 0-23 range")

                            # Main 8hr Shift
                            summary_main = "Work Shift (8hr) (AOA)"
                            main_duration = 8
                            naive_start_main = datetime.datetime.strptime(f"{current_date_str} {aoa_start_hour:02d}:00", "%m/%d/%Y %H:%M")
                            aware_start_main = naive_start_main.replace(tzinfo=SCHEDULE_TZ)
                            aware_end_main = aware_start_main + datetime.timedelta(hours=main_duration)
                            parsed_events.append({
                                "date_str": current_date_str, "start_dt": aware_start_main, "end_dt": aware_end_main,
                                "is_overtime": False, "summary": summary_main })
                            current_app.logger.info(f"Added AOA Main Shift for {current_date_str} starting {aoa_start_hour}:00.")

                            # Separate 2hr OT Shift (After)
                            summary_ot = "Overtime (AOA)"
                            ot_duration = 2
                            aware_start_ot = aware_end_main # OT starts when main shift ends
                            aware_end_ot = aware_start_ot + datetime.timedelta(hours=ot_duration)
                            parsed_events.append({
                                "date_str": current_date_str, "start_dt": aware_start_ot, "end_dt": aware_end_ot,
                                "is_overtime": True, "summary": summary_ot })
                            current_app.logger.info(f"Added AOA OT for {current_date_str} from {aware_start_ot.strftime('%H:%M')} to {aware_end_ot.strftime('%H:%M')}.")

                        elif is_aob:
                            # --- Handle At-Or-Before (AOB<HH>) ---
                            aob_main_start_hour_str = indicator_match.group(10) # Main shift starts at HH
                            aob_main_start_hour = int(aob_main_start_hour_str)
                            if not (0 <= aob_main_start_hour <= 23): raise ValueError("AOB hour outside 0-23 range")

                            # Main shift start time calculation
                            main_start_naive = datetime.datetime.strptime(f"{current_date_str} {aob_main_start_hour:02d}:00", "%m/%d/%Y %H:%M")
                            main_start_aware = main_start_naive.replace(tzinfo=SCHEDULE_TZ)

                            # OT 2hr Shift (Before)
                            summary_ot = "Overtime (AOB)"
                            ot_duration = 2
                            aware_start_ot = main_start_aware - datetime.timedelta(hours=ot_duration) # OT starts 2 hrs before main shift
                            aware_end_ot = main_start_aware # OT ends when main shift starts
                            parsed_events.append({
                                "date_str": current_date_str, "start_dt": aware_start_ot, "end_dt": aware_end_ot,
                                "is_overtime": True, "summary": summary_ot })
                            current_app.logger.info(f"Added AOB OT for {current_date_str} from {aware_start_ot.strftime('%H:%M')} to {aware_end_ot.strftime('%H:%M')}.")

                            # Main 8hr Shift
                            summary_main = "Work Shift (8hr) (AOB)"
                            main_duration = 8
                            aware_end_main = main_start_aware + datetime.timedelta(hours=main_duration)
                            parsed_events.append({
                                "date_str": current_date_str, "start_dt": main_start_aware, "end_dt": aware_end_main,
                                "is_overtime": False, "summary": summary_main })
                            current_app.logger.info(f"Added AOB Main Shift for {current_date_str} starting {aob_main_start_hour}:00.")

                        elif start_hour_str:
                            # --- Handle Regular Work Shift (Digits, TEN, $) ---
                            start_hour = int(start_hour_str)
                            if not (0 <= start_hour <= 23): raise ValueError("Work Shift hour outside 0-23 range")

                            is_ten_hour = is_ten_hour_shift # Use the captured group
                            is_overtime = is_overtime_marker_shift # Use the captured group
                            duration_hours = 10 if is_ten_hour else 8

                            naive_start_dt = datetime.datetime.strptime(f"{current_date_str} {start_hour:02d}:00", "%m/%d/%Y %H:%M")
                            aware_start_dt = naive_start_dt.replace(tzinfo=SCHEDULE_TZ)
                            aware_end_dt = aware_start_dt + datetime.timedelta(hours=duration_hours)

                            summary = f"Work Shift ({duration_hours}hr)"
                            if is_overtime: summary += " (OT)"

                            parsed_events.append({
                                "date_str": current_date_str, "start_dt": aware_start_dt, "end_dt": aware_end_dt,
                                "is_overtime": is_overtime, "summary": summary })
                            log_indicator = f"{start_hour_str}{'TEN' if is_ten_hour else ''}{'$' if is_overtime else ''}"
                            current_app.logger.info(f"Added Work Shift for {current_date_str} ({duration_hours}hr) indicator: {log_indicator}")

                        else: # Should not be reached if regex is correct
                            current_app.logger.warning(f"Indicator matched but no known pattern captured for {current_date_str} on line '{indicator_line}'")

                    except ValueError as e:
                        current_app.logger.error(f"Failed parsing indicator value on line '{indicator_line}' for date {current_date_str}: {e}")
                    except Exception as e_dt:
                        current_app.logger.error(f"Failed creating datetime for {current_date_str} from line '{indicator_line}': {e_dt}", exc_info=True)

                    # Indicator processed (or skipped/errored), break inner loop and clear date
                    current_date_str = None
                    break # Exit the inner while loop
                else:
                    # Line after date wasn't blank/indicator. Check if it's next date line.
                    next_date_match = date_pattern.search(indicator_line)
                    if next_date_match:
                        i -= 1 # Reprocess this line in outer loop
                        current_app.logger.debug("Indicator not found, assuming next line is a date. Breaking inner loop.")
                        current_date_str = None # Discard date
                        break # Exit inner loop
                    else:
                        current_app.logger.debug(f"Ignoring non-indicator/non-date line: '{indicator_line}'")
                        continue # Continue inner loop
            # End of inner while loop

            if not indicator_found and current_date_str:
                current_app.logger.warning(f"Found date {current_date_str} but no subsequent indicator line found.")
                current_date_str = None

        # else: Line didn't contain a date

    current_app.logger.info(f"--- Finished parsing, found {len(parsed_events)} events ---")
    return parsed_events

# --- End of /var/www/postwmt/app/parser.py ---