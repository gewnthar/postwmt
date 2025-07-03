# /var/www/postwmt/app/parser.py
import re
import datetime
from dateutil import tz
from flask import current_app

def parse_schedule_text(text_schedule: str) -> list:
    """
    Parses raw schedule text into a list of events, handling:
    - 8/10-hour shifts (TEN marker)
    - Overtime ($ marker on normal/TEN shifts)
    - RDO (X - skipped)
    - Annual Leave (A<HH> - creates 8hr event 'Annual Leave' starting at HH)
    - At-Or-After OT (AOA<HH> - creates 8hr shift + 2hr OT event after)
    - At-Or-Before OT (AOB<HH> - creates 2hr OT event before + 8hr shift)
    """
    current_app.logger.info("--- Starting schedule parsing (v4.2: Final) ---")
    date_pattern = re.compile(r"(\d{2}/\d{2}/\d{4})")
    indicator_pattern = re.compile(r"^\s*(?:(\d{1,2})(TEN)?(\$)?|(X)|(A<(\d{1,2})>)|(AOA<(\d{1,2})>)|(AOB<(\d{1,2})>))\s*")

    lines = text_schedule.strip().split('\n')
    parsed_events = []
    current_date_str = None
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
        i += 1
        if not line: continue
        date_match = date_pattern.search(line)

        if date_match:
            current_date_str = date_match.group(1)
            current_app.logger.debug(f"Parser found date: {current_date_str}")
            indicator_found = False
            while i < len(lines):
                indicator_line = lines[i].strip()
                i += 1
                if not indicator_line: continue
                indicator_match = indicator_pattern.match(indicator_line)
                if indicator_match:
                    indicator_found = True
                    current_app.logger.debug(f"Parser found indicator line: '{indicator_line}' for date {current_date_str}")
                    
                    start_hour_str, is_ten_hour_shift, is_overtime_marker_shift, is_rdo_marker, _, annual_leave_hour_str, _, aoa_start_hour_str, _, aob_main_start_hour_str = indicator_match.groups()

                    try:
                        if is_rdo_marker:
                            current_app.logger.info(f"RDO (X) detected for {current_date_str}. Skipping event.")
                        
                        elif annual_leave_hour_str is not None:
                            annual_leave_hour = int(annual_leave_hour_str)
                            if not (0 <= annual_leave_hour <= 23): raise ValueError("Annual Leave hour invalid")
                            summary = "Annual Leave"
                            naive_start_dt = datetime.datetime.strptime(f"{current_date_str} {annual_leave_hour:02d}:00", "%m/%d/%Y %H:%M")
                            aware_start_dt = naive_start_dt.replace(tzinfo=SCHEDULE_TZ)
                            aware_end_dt = aware_start_dt + datetime.timedelta(hours=8)
                            parsed_events.append({"date_str": current_date_str, "start_dt": aware_start_dt, "end_dt": aware_end_dt, "is_overtime": False, "summary": summary})
                            current_app.logger.info(f"Added Annual Leave event for {current_date_str} starting {annual_leave_hour}:00 (8hr).")

                        elif aoa_start_hour_str is not None:
                            aoa_start_hour = int(aoa_start_hour_str)
                            if not (0 <= aoa_start_hour <= 23): raise ValueError("AOA hour invalid")
                            main_start = datetime.datetime.strptime(f"{current_date_str} {aoa_start_hour:02d}:00", "%m/%d/%Y %H:%M").replace(tzinfo=SCHEDULE_TZ)
                            main_end = main_start + datetime.timedelta(hours=8)
                            parsed_events.append({"date_str": current_date_str, "start_dt": main_start, "end_dt": main_end, "is_overtime": False, "summary": "Work Shift (8hr) (AOA)"})
                            ot_start = main_end
                            ot_end = ot_start + datetime.timedelta(hours=2)
                            parsed_events.append({"date_str": current_date_str, "start_dt": ot_start, "end_dt": ot_end, "is_overtime": True, "summary": "Overtime (AOA)"})
                            current_app.logger.info(f"Added AOA shift for {current_date_str} at {aoa_start_hour}:00 with subsequent OT.")

                        elif aob_main_start_hour_str is not None:
                            aob_start_hour = int(aob_main_start_hour_str)
                            if not (0 <= aob_start_hour <= 23): raise ValueError("AOB hour invalid")
                            main_start_aware = datetime.datetime.strptime(f"{current_date_str} {aob_start_hour:02d}:00", "%m/%d/%Y %H:%M").replace(tzinfo=SCHEDULE_TZ)
                            # OT Shift (Before)
                            ot_start = main_start_aware - datetime.timedelta(hours=2)
                            parsed_events.append({"date_str": current_date_str, "start_dt": ot_start, "end_dt": main_start_aware, "is_overtime": True, "summary": "Overtime (AOB)"})
                            # Main Shift
                            main_end = main_start_aware + datetime.timedelta(hours=8)
                            parsed_events.append({"date_str": current_date_str, "start_dt": main_start_aware, "end_dt": main_end, "is_overtime": False, "summary": "Work Shift (8hr) (AOB)"})
                            current_app.logger.info(f"Added AOB shift for {current_date_str} at {aob_start_hour}:00 with preceding OT.")

                        elif start_hour_str is not None:
                            start_hour = int(start_hour_str)
                            if not (0 <= start_hour <= 23): raise ValueError("Work shift hour invalid")
                            duration = 10 if is_ten_hour_shift else 8
                            is_ot = bool(is_overtime_marker_shift)
                            summary = f"Work Shift ({duration}hr){' (OT)' if is_ot else ''}"
                            naive_start = datetime.datetime.strptime(f"{current_date_str} {start_hour:02d}:00", "%m/%d/%Y %H:%M")
                            aware_start = naive_start.replace(tzinfo=SCHEDULE_TZ)
                            aware_end = aware_start + datetime.timedelta(hours=duration)
                            parsed_events.append({"date_str": current_date_str, "start_dt": aware_start, "end_dt": aware_end, "is_overtime": is_ot, "summary": summary})
                            current_app.logger.info(f"Added Work Shift for {current_date_str} at {start_hour}:00.")
                    
                    except (ValueError, TypeError) as e:
                        current_app.logger.error(f"Error processing indicator '{indicator_line}' for {current_date_str}: {e}")
                    
                    current_date_str = None; break
                else:
                    if date_pattern.search(indicator_line):
                        i -= 1; current_date_str = None; break
                    else: continue
            if not indicator_found and current_date_str:
                current_app.logger.warning(f"Date {current_date_str} found but no indicator followed.")
                current_date_str = None
    
    current_app.logger.info(f"--- Finished parsing, found {len(parsed_events)} events ---")
    return parsed_events