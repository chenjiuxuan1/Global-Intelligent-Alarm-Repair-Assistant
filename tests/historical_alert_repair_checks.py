import importlib.util
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "core" / "historical_alert_repair.py"


def load_module(country="ine"):
    fake_config_config = types.ModuleType("config.config")
    fake_config_config.HISTORICAL_REPAIR_CONFIG = {
        "host": "sr.example", "port": 9030, "user": "user", "password": "password",
        "database": "testdb", "table": "intelligent_alarm_repair_queue",
        "idle_poll_seconds": 300, "idle_max_wait_seconds": 600, "batch_size": 1,
    }
    fake_config_config.TABLE_CONFIG = {"quality_result_table": "wattrel_quality_result"}
    fake_repair = types.ModuleType("core.repair_strict_7step")
    fake_repair.PROJECT_CODE = "project"
    fake_repair.normalize_to_datetime = lambda value: value if hasattr(value, "strftime") else None
    fake_repair.resolve_repair_table = lambda row: row.get("dest_tbl") or row.get("src_tbl")
    previous_config = sys.modules.get("config.config")
    previous_repair = sys.modules.get("core.repair_strict_7step")
    sys.modules["config.config"] = fake_config_config
    sys.modules["core.repair_strict_7step"] = fake_repair
    try:
        with mock.patch.dict("os.environ", {"APP_COUNTRY": country}, clear=False):
            spec = importlib.util.spec_from_file_location("historical_alert_repair", MODULE_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    finally:
        if previous_config is None:
            sys.modules.pop("config.config", None)
        else:
            sys.modules["config.config"] = previous_config
        if previous_repair is None:
            sys.modules.pop("core.repair_strict_7step", None)
        else:
            sys.modules["core.repair_strict_7step"] = previous_repair


class HistoricalAlertRepairTests(unittest.TestCase):
    def test_classifies_by_data_update_time(self):
        module = load_module()
        now = datetime(2026, 8, 20)
        self.assertEqual(module.classify_alert({"end": datetime(2026, 8, 20)}, now), "seven_days")
        self.assertEqual(module.classify_alert({"end": datetime(2026, 6, 20)}, now), "ninety_days")
        self.assertEqual(module.classify_alert({"end": datetime(2025, 10, 20)}, now), "one_year")
        self.assertEqual(module.classify_alert({"end": datetime(2025, 8, 1)}, now), "out_of_scope")

    def test_due_schedule_is_daily_weekend_and_month_start(self):
        module = load_module()
        monday = datetime(2026, 8, 17)
        sunday = datetime(2026, 8, 23)
        month_start = datetime(2026, 9, 1)
        self.assertTrue(module.class_is_due("seven_days", monday))
        self.assertFalse(module.class_is_due("ninety_days", monday))
        self.assertTrue(module.class_is_due("ninety_days", sunday))
        self.assertFalse(module.class_is_due("one_year", sunday))
        self.assertTrue(module.class_is_due("one_year", month_start))

    def test_excess_data_is_manual_review(self):
        module = load_module()
        self.assertTrue(module.diff_is_excess(-1))
        self.assertFalse(module.diff_is_excess(1))
        self.assertFalse(module.diff_is_excess("unknown"))

    def test_china_does_not_enable_testdb_queue(self):
        module = load_module(country="cn")
        self.assertFalse(module.queue_enabled())


if __name__ == "__main__":
    unittest.main()
