import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "extract_ds_sh_usage.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_ds_sh_usage", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExtractDsShUsageTests(unittest.TestCase):
    def test_collects_sh_from_resource_list(self):
        module = load_module()
        task = {
            "name": "shell_task",
            "code": "100",
            "taskType": "SHELL",
            "taskParams": {
                "resourceList": [
                    {"fullName": "/prod/script/run_a.sh"},
                    {"fullName": "/prod/script/readme.txt"},
                ]
            },
        }

        usages = module.extract_sh_references_from_task(task)

        self.assertEqual(len(usages), 1)
        self.assertEqual(usages[0]["reference_type"], "resourceList")
        self.assertEqual(usages[0]["script_path"], "/prod/script/run_a.sh")

    def test_collects_sh_from_raw_script(self):
        module = load_module()
        task = {
            "name": "shell_task",
            "code": "101",
            "taskType": "SHELL",
            "taskParams": {
                "rawScript": "bash /opt/jobs/run_daily.sh\nsh ./child.sh\npython app.py"
            },
        }

        usages = module.extract_sh_references_from_task(task)

        self.assertEqual(
            {(item["reference_type"], item["script_path"]) for item in usages},
            {
                ("rawScript", "/opt/jobs/run_daily.sh"),
                ("rawScript", "./child.sh"),
            },
        )

    def test_collects_sh_from_string_params(self):
        module = load_module()
        task = {
            "name": "dependent_task",
            "code": "102",
            "taskType": "SHELL",
            "taskParams": {
                "mainJar": "ignore.jar",
                "command": "/data/app/start_sync.sh --date 2026-03-30",
            },
        }

        usages = module.extract_sh_references_from_task(task)

        self.assertEqual(len(usages), 1)
        self.assertEqual(usages[0]["reference_type"], "param.command")
        self.assertEqual(usages[0]["script_path"], "/data/app/start_sync.sh")

    def test_build_usage_rows_adds_workflow_context(self):
        module = load_module()
        workflow = {"name": "wf_a", "code": "200", "releaseState": "ONLINE"}
        detail = {
            "taskDefinitionList": [
                {
                    "name": "task_a",
                    "code": "300",
                    "taskType": "SHELL",
                    "taskParams": {"rawScript": "sh run_me.sh"},
                }
            ]
        }
        schedule_map = {"200": {"schedule_status": "ONLINE", "schedule_cron": "0 0 * * * ?"}}

        rows = module.build_workflow_sh_rows("DW_DM", "116", workflow, detail, schedule_map)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project_name"], "DW_DM")
        self.assertEqual(rows[0]["workflow_name"], "wf_a")
        self.assertEqual(rows[0]["task_name"], "task_a")
        self.assertEqual(rows[0]["script_path"], "run_me.sh")


if __name__ == "__main__":
    unittest.main()
