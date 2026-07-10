import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "config" / "config.py"


def load_module():
    spec = importlib.util.spec_from_file_location("runtime_config_profile_test", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CountryProfileLoaderTests(unittest.TestCase):
    def test_app_country_loads_country_profile_when_values_are_missing(self):
        with mock.patch.dict(os.environ, {"APP_COUNTRY": "th", "APP_ENV_FILE": "/tmp/missing.env"}, clear=True):
            module = load_module()

        self.assertEqual(module.DS_CONFIG["api_mode"], "auto")
        self.assertEqual(
            module.DB_CONFIG["host"],
            "rm-gs533qw7xj1e7wdp7.mysql.singapore.rds.aliyuncs.com",
        )
        self.assertEqual(module.DB_CONFIG["port"], 3306)
        self.assertEqual(module.DB_CONFIG["user"], "a_dolphinscheduler")

    def test_process_environment_overrides_country_profile(self):
        env = {
            "APP_COUNTRY": "th",
            "APP_ENV_FILE": "/tmp/missing.env",
            "DB_HOST": "override-host",
            "DS_API_MODE": "process_v2",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            module = load_module()

        self.assertEqual(module.DB_CONFIG["host"], "override-host")
        self.assertEqual(module.DS_CONFIG["api_mode"], "process_v2")

    def test_country_alias_is_normalized(self):
        with mock.patch.dict(os.environ, {"COUNTRY": "philippines", "APP_ENV_FILE": "/tmp/missing.env"}, clear=True):
            module = load_module()

        self.assertEqual(module.DS_CONFIG["api_mode"], "process_v2")
        self.assertEqual(module.DS_CONFIG["start_endpoint"], "start-process-instance")


if __name__ == "__main__":
    unittest.main()
