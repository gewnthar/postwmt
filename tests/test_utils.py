import unittest
import datetime
from dateutil import tz
from app.utils import create_ics_content
from flask import Flask # Required for app context

# Define the expected timezone for consistency
SCHEDULE_TZ_NAME = 'America/New_York'
SCHEDULE_TZ = tz.gettz(SCHEDULE_TZ_NAME)

class TestUtils(unittest.TestCase):

    def setUp(self):
        # Flask app context is needed for current_app.logger used in utils
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_create_ics_empty_list(self):
        ics_content = create_ics_content([])
        self.assertIn("BEGIN:VCALENDAR", ics_content)
        self.assertIn("END:VCALENDAR", ics_content)
        self.assertNotIn("BEGIN:VEVENT", ics_content) # No events

    def test_create_ics_single_event(self):
        start_dt = datetime.datetime(2024, 5, 1, 10, 0, 0, tzinfo=SCHEDULE_TZ)
        end_dt = start_dt + datetime.timedelta(hours=8)
        events = [
            {
                "summary": "Test Work Shift",
                "start_dt": start_dt,
                "end_dt": end_dt,
                "date_str": "05/01/2024", # For logging, not directly in ICS event typically
                "is_overtime": False
            }
        ]
        ics_content = create_ics_content(events)
        self.assertIn("BEGIN:VCALENDAR", ics_content)
        self.assertIn("BEGIN:VEVENT", ics_content)
        self.assertIn("SUMMARY:Test Work Shift", ics_content)
        # Check for DTSTART and DTEND in UTC, as ics.py library converts aware datetimes to UTC
        # Example: 20240501T100000-0400 (America/New_York) becomes 20240501T140000Z (UTC)
        start_utc = start_dt.astimezone(tz.tzutc())
        end_utc = end_dt.astimezone(tz.tzutc())
        self.assertIn(f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}", ics_content)
        self.assertIn(f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}", ics_content)
        self.assertIn("END:VEVENT", ics_content)
        self.assertIn("END:VCALENDAR", ics_content)

    def test_create_ics_multiple_events(self):
        events = [
            {
                "summary": "Morning Shift",
                "start_dt": datetime.datetime(2024, 5, 2, 8, 0, 0, tzinfo=SCHEDULE_TZ),
                "end_dt": datetime.datetime(2024, 5, 2, 16, 0, 0, tzinfo=SCHEDULE_TZ),
                "date_str": "05/02/2024"
            },
            {
                "summary": "Night Shift",
                "start_dt": datetime.datetime(2024, 5, 3, 22, 0, 0, tzinfo=SCHEDULE_TZ),
                "end_dt": datetime.datetime(2024, 5, 4, 6, 0, 0, tzinfo=SCHEDULE_TZ), # Spans midnight
                "date_str": "05/03/2024"
            }
        ]
        ics_content = create_ics_content(events)
        self.assertIn("SUMMARY:Morning Shift", ics_content)
        self.assertIn("SUMMARY:Night Shift", ics_content)
        self.assertEqual(ics_content.count("BEGIN:VEVENT"), 2)

    def test_event_with_missing_datetime(self):
        # Event missing end_dt
        events = [
            {
                "summary": "Incomplete Event",
                "start_dt": datetime.datetime(2024, 5, 4, 10, 0, 0, tzinfo=SCHEDULE_TZ),
                "date_str": "05/04/2024"
                # end_dt is missing
            }
        ]
        ics_content = create_ics_content(events)
        self.assertNotIn("SUMMARY:Incomplete Event", ics_content) # Event should be skipped

    def test_event_with_naive_datetime(self):
        # Event with naive datetime (no tzinfo)
        events = [
            {
                "summary": "Naive Event",
                "start_dt": datetime.datetime(2024, 5, 5, 10, 0, 0), # Naive
                "end_dt": datetime.datetime(2024, 5, 5, 18, 0, 0),   # Naive
                "date_str": "05/05/2024"
            }
        ]
        ics_content = create_ics_content(events)
        # The create_ics_content function logs an error and skips naive datetimes.
        self.assertNotIn("SUMMARY:Naive Event", ics_content)

if __name__ == '__main__':
    unittest.main()
