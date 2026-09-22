import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class AppTests(unittest.TestCase):
    def test_startup_and_threshold_controls(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "耕地地块周边地物分析工具")
        self.assertTrue(next(b for b in app.button if b.label == "开始分析").disabled)
        self.assertTrue(next(n for n in app.number_input if n.label == "最大距离（米）").disabled)
        app.checkbox[0].check().run()
        self.assertFalse(next(n for n in app.number_input if n.label == "最大距离（米）").disabled)
        self.assertEqual(len(app.exception), 0)
