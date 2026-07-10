import csv
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "extract_ds_sql.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_ds_sql", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExtractDsSqlTests(unittest.TestCase):
    def test_module_can_be_imported_locally(self):
        module = load_module()
        self.assertTrue(hasattr(module, "extract_sql_from_workflow"))

    def test_extract_sql_from_workflow_supports_sql_and_raw_script(self):
        module = load_module()
        workflow_detail = {
            "processDefinition": {"name": "wf_online", "code": "1001"},
            "taskDefinitionList": [
                {
                    "name": "sql_node",
                    "code": "2001",
                    "taskType": "SQL",
                    "taskParams": {"sql": "select * from dw_dm.sample_table"},
                },
                {
                    "name": "shell_sql_node",
                    "code": "2002",
                    "taskType": "SQL",
                    "taskParams": {"rawScript": "insert overwrite table ads.result select * from dim.user"},
                },
                {
                    "name": "python_node",
                    "code": "2003",
                    "taskType": "PYTHON",
                    "taskParams": {"rawScript": "print('skip')"},
                },
            ],
        }

        sql_tasks = module.extract_sql_from_workflow(workflow_detail)

        self.assertEqual([task["task_name"] for task in sql_tasks], ["sql_node", "shell_sql_node"])
        self.assertEqual(sql_tasks[0]["sql"], "select * from dw_dm.sample_table")
        self.assertEqual(
            sql_tasks[1]["sql"],
            "insert overwrite table ads.result select * from dim.user",
        )

    def test_filter_online_workflows_only_keeps_online(self):
        module = load_module()
        workflows = [
            {"name": "wf1", "code": "1", "releaseState": "ONLINE"},
            {"name": "wf2", "code": "2", "releaseState": "OFFLINE"},
            {"name": "wf3", "code": "3", "releaseState": "online"},
        ]

        online = module.filter_online_workflows(workflows)

        self.assertEqual([item["code"] for item in online], ["1", "3"])

    def test_detect_database_folder_from_sql(self):
        module = load_module()

        self.assertEqual(module.detect_target_database("insert into dw_dm.orders select 1"), "dw_dm")
        self.assertEqual(
            module.detect_target_database("insert into dw_dm.orders select * from ods.user join dim.city"),
            "mixed",
        )
        self.assertEqual(module.detect_target_database("select 1"), "unknown_db")

    def test_write_sql_file_uses_database_folder_and_task_name(self):
        module = load_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            task = {
                "workflow_name": "DW_DM_WF",
                "workflow_code": "1001",
                "task_name": "node_a",
                "task_code": "2001",
                "task_type": "SQL",
                "datasource": "dw_dm",
                "sql": "insert overwrite table dw_dm.orders select 1",
                "database_name": "dw_dm",
            }

            file_path = module.save_sql_task(task, temp_dir)

            self.assertTrue(file_path.endswith(os.path.join("dw_dm", "node_a.sql")))
            self.assertTrue(os.path.exists(file_path))
            with open(file_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("-- Workflow: DW_DM_WF", content)
            self.assertIn("insert overwrite table dw_dm.orders", content)

    def test_write_status_report_generates_csv_rows(self):
        module = load_module()
        rows = [
            {
                "project_name": "DW_DM",
                "project_code": "123",
                "workflow_name": "wf1",
                "workflow_code": "1001",
                "workflow_release_state": "ONLINE",
                "schedule_status": "ONLINE",
                "task_name": "node_a",
                "task_code": "2001",
                "task_type": "SQL",
                "database_name": "dw_dm",
                "sql_source": "sql",
                "sql_length": 33,
                "output_file": "dw_dm/node_a.sql",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "status.csv")
            module.write_status_report(rows, report_path)

            self.assertTrue(os.path.exists(report_path))
            with open(report_path, "r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                data = list(reader)

            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["project_name"], "DW_DM")
            self.assertEqual(data[0]["database_name"], "dw_dm")


if __name__ == "__main__":
    unittest.main()
