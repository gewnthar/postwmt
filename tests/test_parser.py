import unittest
import datetime
from dateutil import tz
from app.parser import parse_schedule_text
from flask import Flask # Required for app context

# Define the expected timezone for consistency with the parser
SCHEDULE_TZ_NAME = 'America/New_York'
SCHEDULE_TZ = tz.gettz(SCHEDULE_TZ_NAME)

class TestScheduleParser(unittest.TestCase):

    def setUp(self):
        # Flask app context is needed for current_app.logger used in parser
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        # You might need to set other config values if your parser depends on them
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_empty_input(self):
        self.assertEqual(parse_schedule_text(""), [])

    def test_simple_8hr_shift(self):
        # Date: 04/15/2024, Shift: 21:00 (8-hour)
        schedule_text = "04/15/2024 Mon\n21"
        expected_start = datetime.datetime(2024, 4, 15, 21, 0, tzinfo=SCHEDULE_TZ)
        expected_end = datetime.datetime(2024, 4, 15, 21, 0, tzinfo=SCHEDULE_TZ) + datetime.timedelta(hours=8)
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['summary'], "Work Shift (8hr)")
        self.assertEqual(result[0]['start_dt'], expected_start)
        self.assertEqual(result[0]['end_dt'], expected_end)
        self.assertFalse(result[0]['is_overtime'])

    def test_simple_10hr_shift(self):
        # Date: 04/16/2024, Shift: 08:00 (10-hour)
        schedule_text = "04/16/2024 Tue\n08TEN"
        expected_start = datetime.datetime(2024, 4, 16, 8, 0, tzinfo=SCHEDULE_TZ)
        expected_end = datetime.datetime(2024, 4, 16, 8, 0, tzinfo=SCHEDULE_TZ) + datetime.timedelta(hours=10)
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['summary'], "Work Shift (10hr)")
        self.assertEqual(result[0]['start_dt'], expected_start)
        self.assertEqual(result[0]['end_dt'], expected_end)
        self.assertFalse(result[0]['is_overtime'])

    def test_overtime_shift(self):
        # Date: 04/17/2024, Shift: 21:00 (8-hour, Overtime)
        schedule_text = "04/17/2024 Wed\n21$"
        expected_start = datetime.datetime(2024, 4, 17, 21, 0, tzinfo=SCHEDULE_TZ)
        expected_end = datetime.datetime(2024, 4, 17, 21, 0, tzinfo=SCHEDULE_TZ) + datetime.timedelta(hours=8)
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['summary'], "Work Shift (8hr) (OT)")
        self.assertEqual(result[0]['start_dt'], expected_start)
        self.assertEqual(result[0]['end_dt'], expected_end)
        self.assertTrue(result[0]['is_overtime'])

    def test_10hr_overtime_shift(self):
        # Date: 04/18/2024, Shift: 07:00 (10-hour, Overtime)
        schedule_text = "04/18/2024 Thu\n07TEN$"
        expected_start = datetime.datetime(2024, 4, 18, 7, 0, tzinfo=SCHEDULE_TZ)
        expected_end = datetime.datetime(2024, 4, 18, 7, 0, tzinfo=SCHEDULE_TZ) + datetime.timedelta(hours=10)
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['summary'], "Work Shift (10hr) (OT)")
        self.assertEqual(result[0]['start_dt'], expected_start)
        self.assertEqual(result[0]['end_dt'], expected_end)
        self.assertTrue(result[0]['is_overtime'])

    def test_day_off(self):
        # Date: 04/19/2024, Day Off
        schedule_text = "04/19/2024 Fri\nX"
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 0) # Day off means no event entry

    def test_multiple_entries(self):
        schedule_text = (
            "04/20/2024 Sat\n09\n"  # 8hr
            "04/21/2024 Sun\nX\n"   # Off
            "04/22/2024 Mon\n14TEN$\n" # 10hr OT
            "Some other text\n"
            "04/23/2024 Tue\n08TEN" # 10hr
        )
        results = parse_schedule_text(schedule_text)
        self.assertEqual(len(results), 3)

        # Check first event (04/20)
        self.assertEqual(results[0]['summary'], "Work Shift (8hr)")
        self.assertEqual(results[0]['start_dt'], datetime.datetime(2024, 4, 20, 9, 0, tzinfo=SCHEDULE_TZ))
        self.assertFalse(results[0]['is_overtime'])

        # Check second event (04/22) - 04/21 was X (day off)
        self.assertEqual(results[1]['summary'], "Work Shift (10hr) (OT)")
        self.assertEqual(results[1]['start_dt'], datetime.datetime(2024, 4, 22, 14, 0, tzinfo=SCHEDULE_TZ))
        self.assertTrue(results[1]['is_overtime'])

        # Check third event (04/23)
        self.assertEqual(results[2]['summary'], "Work Shift (10hr)")
        self.assertEqual(results[2]['start_dt'], datetime.datetime(2024, 4, 23, 8, 0, tzinfo=SCHEDULE_TZ))
        self.assertFalse(results[2]['is_overtime'])


    def test_invalid_hour(self):
        schedule_text = "04/24/2024 Wed\n99" # Invalid hour
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 0) # Should not parse if hour is invalid

    def test_malformed_date_line(self):
        schedule_text = "This is not a date\n21"
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 0)

    def test_date_without_indicator(self):
        schedule_text = "04/25/2024 Thu\nSome random text instead of hour/X"
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 0)

    def test_indicator_without_date(self):
        schedule_text = "21TEN$"
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 0)

    def test_extra_whitespace_and_text(self):
        schedule_text = "  04/26/2024 Fri    Some trailing text on date line\n  \t22TEN  Extra text after indicator"
        expected_start = datetime.datetime(2024, 4, 26, 22, 0, tzinfo=SCHEDULE_TZ)
        expected_end = expected_start + datetime.timedelta(hours=10)
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['summary'], "Work Shift (10hr)")
        self.assertEqual(result[0]['start_dt'], expected_start)
        self.assertEqual(result[0]['end_dt'], expected_end)

    def test_blank_lines_between_date_and_indicator(self):
        schedule_text = "04/27/2024 Sat\n\n\n06$"
        expected_start = datetime.datetime(2024, 4, 27, 6, 0, tzinfo=SCHEDULE_TZ)
        expected_end = expected_start + datetime.timedelta(hours=8)
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['summary'], "Work Shift (8hr) (OT)")
        self.assertEqual(result[0]['start_dt'], expected_start)
        self.assertEqual(result[0]['end_dt'], expected_end)

    def test_date_followed_by_another_date_no_indicator(self):
        schedule_text = (
            "04/28/2024 Sun (No indicator here)\n"
            "04/29/2024 Mon\n10"
        )
        result = parse_schedule_text(schedule_text)
        self.assertEqual(len(result), 1) # Only the second date should parse
        self.assertEqual(result[0]['date_str'], "04/29/2024")
        self.assertEqual(result[0]['start_dt'], datetime.datetime(2024, 4, 29, 10, 0, tzinfo=SCHEDULE_TZ))


if __name__ == '__main__':
    unittest.main()
