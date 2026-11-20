"""Broadcast CSV upload must find the phone column even when it isn't literally called "phone".

Kelir's file used "MOBILE NUMBER": no phone column was found, every lead went out with a
blank phone and the send failed with "No eligible leads".
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes.upload import _count_unique_phones, _suggest_mapping


class SuggestMappingTests(unittest.TestCase):
    def test_kelir_mobile_number_header(self):
        m = _suggest_mapping(["MOBILE NUMBER", "NAME", "", ""])
        self.assertEqual(m["phone"], "MOBILE NUMBER")
        self.assertEqual(m["name"], "NAME")

    def test_common_phone_headers(self):
        for col in ("Phone", "phone_number", "Mobile", "WhatsApp No", "Contact", "Number", "Cell"):
            with self.subTest(col=col):
                self.assertEqual(_suggest_mapping(["Name", col])["phone"], col)

    def test_phone_beats_vaguer_columns(self):
        m = _suggest_mapping(["Order Number", "Contact Name", "Phone"])
        self.assertEqual(m["phone"], "Phone")

    def test_name_or_email_column_is_never_the_phone(self):
        m = _suggest_mapping(["Contact Name", "Contact Email", "Number"])
        self.assertEqual(m["phone"], "Number")

    def test_no_phone_like_column(self):
        self.assertIsNone(_suggest_mapping(["Name", "City"])["phone"])

    def test_other_fields_unchanged(self):
        m = _suggest_mapping(["Full Name", "Email ID", "Course", "Phone"])
        self.assertEqual(m, {"name": "Full Name", "phone": "Phone", "email": "Email ID", "course": "Course"})



class CountUniquePhonesTests(unittest.TestCase):
    """The Confirm & Send note: '139 rows, 74 unique numbers will be messaged'."""

    def test_same_number_in_different_formats_counts_once(self):
        rows = [{"MOBILE NUMBER": v} for v in ("'+919876543210", "9876543210", "91 98765 43210", "+919876543211")]
        self.assertEqual(_count_unique_phones(rows, "MOBILE NUMBER"), 2)

    def test_blank_and_invalid_numbers_are_not_counted(self):
        rows = [{"Phone": v} for v in ("", "abc", "12", "9876543210")] + [{}]
        self.assertEqual(_count_unique_phones(rows, "Phone"), 1)

    def test_no_phone_column(self):
        self.assertEqual(_count_unique_phones([{"Name": "A"}], None), 0)


if __name__ == "__main__":
    unittest.main()
