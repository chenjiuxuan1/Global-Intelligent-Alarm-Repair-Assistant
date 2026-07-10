import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "task_execution_checker.py"


def load_module():
    spec = importlib.util.spec_from_file_location("task_execution_checker", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskExecutionCheckerTests(unittest.TestCase):
    def test_checker_falls_back_to_repo_root_when_configured_workspace_is_invalid(self):
        platform_root = str(REPO_ROOT)
        existing_paths = {str(REPO_ROOT / "core" / "repair_strict_7step.py")}

        with mock.patch.dict(os.environ, {"APP_WORKSPACE": "/invalid/workspace"}, clear=False), mock.patch(
            "os.path.exists", side_effect=lambda path: path in existing_paths
        ):
            module = load_module()

        self.assertEqual(
            module.EFFECTIVE_WORKSPACE_ROOT,
            platform_root,
        )
        self.assertTrue(module.check_script_exists("core/repair_strict_7step.py"))


if __name__ == "__main__":
    unittest.main()
