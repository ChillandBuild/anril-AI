"""The broadcast CSV path the client sends must stay inside its own tenant's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from app.routes.upload import _validate_csv_storage_path


class CsvStoragePathTests(unittest.TestCase):
    def test_own_folder_is_accepted(self):
        self.assertEqual(_validate_csv_storage_path("/t1/ab12_leads.csv", "t1"), "t1/ab12_leads.csv")

    def test_other_folders_and_climbing_out_are_refused(self):
        for path in ("t2/x.csv", "t1/../t2/x.csv", "t1/a/../../t2/x.csv", r"t1\..\t2\x.csv", "", "  "):
            with self.subTest(path=path):
                with self.assertRaises(HTTPException) as err:
                    _validate_csv_storage_path(path, "t1")
                self.assertEqual(err.exception.status_code, 403)

    def test_dots_inside_a_file_name_are_fine(self):
        self.assertEqual(_validate_csv_storage_path("t1/leads..v2.csv", "t1"), "t1/leads..v2.csv")


if __name__ == "__main__":
    unittest.main()
