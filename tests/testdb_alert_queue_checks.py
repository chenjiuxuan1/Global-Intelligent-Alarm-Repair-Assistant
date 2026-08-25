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

    def test_ai_uses_validated_srbox_probes_only_for_long_history_alerts(self):
        now = datetime.now()
        config = dict(queue.TESTDB_ALERT_CONFIG)
        config.update({"ai_webhook_url": "https://n8n.example/webhook/test", "srbox_time_location_enabled": True, "srbox_client_path": "client.py"})
        row = {
            "begin": now - timedelta(days=10), "src_tbl": "a", "dest_tbl": "b", "diff": 1,
            "src_sql": "SELECT COUNT(*) FROM db.a WHERE dt >= '2026-01-01' AND dt < '2026-01-02'",
            "dest_sql": "SELECT COUNT(*) FROM db.b WHERE dt >= '2026-01-01' AND dt < '2026-01-02'",
        }
        plan = {"source_probe_sql": "SELECT COUNT(*) FROM db.a WHERE dt >= '2026-01-01' AND dt < '2026-01-02'", "comparison_probe_sql": "SELECT COUNT(*) FROM db.b WHERE dt >= '2026-01-01' AND dt < '2026-01-02'"}
        conclusion = {"precise_anomaly_time": "2026-01-01", "confidence": "high"}
        with mock.patch.object(queue, "TESTDB_ALERT_CONFIG", config), mock.patch.object(queue, "_post_ai", side_effect=[plan, conclusion]) as post_ai, mock.patch.object(queue, "_run_srbox_probe", return_value={"rows": []}) as probe:
            status, analysis, error = queue.analyze_long_anomaly(row, now, [])
            self.assertEqual((status, error), ("complete", ""))
            self.assertIn("precise_anomaly_time", analysis)
            self.assertEqual(queue.analyze_long_anomaly({"end": now - timedelta(days=2)}, now, [])[0], "disabled")
        self.assertEqual(post_ai.call_count, 2)
        self.assertEqual(probe.call_count, 2)

    def test_probe_sql_rejects_writes_and_unknown_tables(self):
        row = {"src_sql": "SELECT COUNT(*) FROM db.a WHERE dt >= '2026-01-01' AND dt < '2026-01-02'", "dest_sql": "SELECT COUNT(*) FROM db.b WHERE dt >= '2026-01-01' AND dt < '2026-01-02'"}
        self.assertTrue(queue._valid_probe_sql("SELECT COUNT(*) FROM db.a WHERE dt >= '2026-01-01' AND dt < '2026-01-02'", row))
        self.assertFalse(queue._valid_probe_sql("DELETE FROM db.a", row))
        self.assertFalse(queue._valid_probe_sql("SELECT COUNT(*) FROM db.secret WHERE dt >= '2026-01-01' AND dt < '2026-01-02'", row))
        self.assertFalse(queue._valid_probe_sql("SELECT COUNT(*) FROM db.a WHERE dt >= '2025-01-01' AND dt < '2025-01-02'", row))


if __name__ == "__main__":
    unittest.main()
