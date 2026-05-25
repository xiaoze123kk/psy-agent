from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.services.temporal_context_service import build_temporal_context


class TemporalContextServiceTests(unittest.TestCase):
    def test_build_temporal_context_uses_asia_wuhan_default(self) -> None:
        context = build_temporal_context(now=datetime(2026, 5, 17, 4, 30, tzinfo=timezone.utc))

        self.assertEqual(context["timezone"], "Asia/Wuhan")
        self.assertEqual(context["local_date"], "2026-05-17")
        self.assertEqual(context["local_time"], "12:30")
        self.assertEqual(context["weekday"], "星期日")
        self.assertEqual(context["day_period"], "中午")
        self.assertIn("午", context["companion_hint"])

    def test_build_temporal_context_marks_late_night_for_sleep_care(self) -> None:
        context = build_temporal_context(now=datetime(2026, 5, 17, 15, 45, tzinfo=timezone.utc))

        self.assertEqual(context["local_time"], "23:45")
        self.assertEqual(context["day_period"], "深夜")
        self.assertIn("别太熬", context["companion_hint"])


if __name__ == "__main__":
    unittest.main()
