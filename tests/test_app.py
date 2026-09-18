import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class AppTests(unittest.TestCase):
    def test_startup_and_threshold_controls(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "耕地地块周边地物分析工具")
        self.assertTrue(app.button[0].disabled)
        self.assertTrue(app.number_input[0].disabled)
        app.checkbox[0].check().run()
        self.assertFalse(app.number_input[0].disabled)
        self.assertEqual(len(app.exception), 0)
