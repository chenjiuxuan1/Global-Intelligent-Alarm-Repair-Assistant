import unittest
from datetime import datetime, timedelta
from unittest import mock

from core import testdb_alert_queue as queue


class TestdbAlertQueueChecks(unittest.TestCase):
    def test_classification_uses_business_window_begin(self):
        now = datetime(2026, 8, 24)
        self.assertEqual(queue.alert_class({"begin": now - timedelta(days=7)}, now), "7d")
        self.assertEqual(queue.alert_class({"begin": now - timedelta(days=8)}, now), "90d")
        self.assertEqual(queue.alert_class({"begin": now - timedelta(days=91)}, now), "1y")
        self.assertEqual(queue.data_date({"begin": now - timedelta(days=20), "end": now - timedelta(days=3)}, now), now - timedelta(days=20))

    def test_diff_labels_missing_and_extra_data(self):
        self.assertEqual(queue.diff_label({"diff": 1}), 1)
        self.assertEqual(queue.diff_label({"diff": -1}), 2)

    def test_audit_key_is_stable_for_the_same_alert_window(self):
        now = datetime(2026, 8, 24)
        row = {"id": 1, "src_tbl": "source", "dest_tbl": "target", "end": now}
        self.assertEqual(queue.audit_key(row, now), queue.audit_key(row, now))

    def test_ai_is_called_only_for_long_history_alerts(self):
        now = datetime.now()
        config = dict(queue.TESTDB_ALERT_CONFIG)
        config.update({"ai_webhook_url": "https://n8n.example/webhook/test", "ai_webhook_token": "token", "ai_timeout_seconds": 5})
        response = mock.MagicMock()
        response.read.return_value = b'{"recommended_rerun_date":"2026-01-01"}'
        context = mock.MagicMock()
        context.__enter__.return_value = response
        with mock.patch.object(queue, "TESTDB_ALERT_CONFIG", config), mock.patch("urllib.request.urlopen", return_value=context) as urlopen:
            status, analysis, error = queue.analyze_long_anomaly({"end": now - timedelta(days=10), "src_tbl": "a", "dest_tbl": "b", "diff": 1}, now, [])
            self.assertEqual((status, error), ("complete", ""))
            self.assertIn("recommended_rerun_date", analysis)
            self.assertEqual(queue.analyze_long_anomaly({"end": now - timedelta(days=2)}, now, [])[0], "disabled")
        urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
