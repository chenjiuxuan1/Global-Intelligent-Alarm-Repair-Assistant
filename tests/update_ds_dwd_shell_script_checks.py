import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "update_ds_dwd_shell_script.py"


def load_module():
    spec = importlib.util.spec_from_file_location("update_ds_dwd_shell_script", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UpdateDsDwdShellScriptTests(unittest.TestCase):
    def test_plan_script_updates_replaces_exact_old_shell_script(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SHELL",
                "taskParams": {"rawScript": module.OLD_SCRIPT},
            },
            {
                "name": "dwd_b",
                "code": 2,
                "taskType": "SHELL",
                "taskParams": {"rawScript": "echo 1"},
            },
        ]

        updated, changes = module.plan_script_updates(
            tasks,
            module.OLD_SCRIPT,
            module.NEW_SCRIPT,
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["task_name"], "dwd_a")
        self.assertEqual(updated[0]["taskParams"]["rawScript"], module.NEW_SCRIPT)
        self.assertEqual(updated[1]["taskParams"]["rawScript"], "echo 1")

    def test_plan_script_updates_can_force_replace_all_shell_scripts(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SHELL",
                "taskParams": {"rawScript": 'python3 $WATTREL_HOME/console.py etl --db=dwd_sec --table=${table} --args="${args}"'},
            },
            {
                "name": "dwd_sql",
                "code": 2,
                "taskType": "SQL",
                "taskParams": {"rawScript": "select 1"},
            },
        ]

        updated, changes = module.plan_script_updates(
            tasks,
            module.OLD_SCRIPT,
            module.NEW_SCRIPT,
            replace_all_shell_scripts=True,
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["task_name"], "dwd_a")
        self.assertEqual(updated[0]["taskParams"]["rawScript"], module.NEW_SCRIPT)
        self.assertEqual(updated[1]["taskParams"]["rawScript"], "select 1")

    def test_plan_script_updates_can_replace_path_prefixes_in_script_and_resources(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SHELL",
                "environmentCode": 11,
                "taskParams": {
                    "rawScript": (
                        "bash pak/sql_job_shell/redo_biz_cli.sh "
                        "pak/dwd_sql_job/dwd_a.sql ${etl_time}"
                    ),
                    "resourceList": [
                        {
                            "resourceName": (
                                "dolphinscheduler/resource/dolphinscheduler/resources/"
                                "pak/sql_job_shell/redo_biz_cli.sh"
                            )
                        },
                        {
                            "resourceName": (
                                "dolphinscheduler/resource/dolphinscheduler/resources/"
                                "pak/dwd_sql_job/dwd_a.sql"
                            )
                        },
                    ],
                },
            }
        ]

        updated, changes = module.plan_script_updates(
            tasks,
            "__no_exact_match__",
            module.NEW_SCRIPT,
            target_environment_code=22,
            raw_script_replacements=[("pak/", "pak_sr/")],
            resource_replacements=[("/pak/", "/pak_sr/")],
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(updated[0]["environmentCode"], 22)
        self.assertEqual(
            updated[0]["taskParams"]["rawScript"],
            "bash pak_sr/sql_job_shell/redo_biz_cli.sh pak_sr/dwd_sql_job/dwd_a.sql ${etl_time}",
        )
        self.assertEqual(
            updated[0]["taskParams"]["resourceList"],
            [
                {
                    "resourceName": (
                        "dolphinscheduler/resource/dolphinscheduler/resources/"
                        "pak_sr/sql_job_shell/redo_biz_cli.sh"
                    )
                },
                {
                    "resourceName": (
                        "dolphinscheduler/resource/dolphinscheduler/resources/"
                        "pak_sr/dwd_sql_job/dwd_a.sql"
                    )
                },
            ],
        )

    def test_plan_script_updates_also_updates_environment_code(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SHELL",
                "environmentCode": 11,
                "taskParams": {"rawScript": module.OLD_SCRIPT},
            }
        ]

        updated, changes = module.plan_script_updates(
            tasks,
            module.OLD_SCRIPT,
            module.NEW_SCRIPT,
            target_environment_code=22,
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["task_name"], "dwd_a")
        self.assertEqual(changes[0]["old_environment_code"], "11")
        self.assertEqual(changes[0]["new_environment_code"], "22")
        self.assertEqual(updated[0]["taskParams"]["rawScript"], module.NEW_SCRIPT)
        self.assertEqual(updated[0]["environmentCode"], 22)

    def test_plan_script_updates_ignores_non_shell_tasks(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_sql",
                "code": 3,
                "taskType": "SQL",
                "taskParams": {"rawScript": module.OLD_SCRIPT},
            }
        ]

        updated, changes = module.plan_script_updates(
            tasks,
            module.OLD_SCRIPT,
            module.NEW_SCRIPT,
        )

        self.assertEqual(changes, [])
        self.assertEqual(updated[0]["taskParams"]["rawScript"], module.OLD_SCRIPT)

    def test_plan_script_updates_can_update_environment_without_script_change(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SHELL",
                "environmentCode": 11,
                "taskParams": {"rawScript": "echo 1"},
            }
        ]

        updated, changes = module.plan_script_updates(
            tasks,
            module.OLD_SCRIPT,
            module.NEW_SCRIPT,
            target_environment_code=22,
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["task_name"], "dwd_a")
        self.assertEqual(changes[0]["old_script"], "echo 1")
        self.assertEqual(changes[0]["new_script"], "echo 1")
        self.assertEqual(updated[0]["taskParams"]["rawScript"], "echo 1")
        self.assertEqual(updated[0]["environmentCode"], 22)

    def test_plan_script_updates_can_target_single_task(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SHELL",
                "taskParams": {"rawScript": module.OLD_SCRIPT},
            },
            {
                "name": "dwd_b",
                "code": 2,
                "taskType": "SHELL",
                "taskParams": {"rawScript": module.OLD_SCRIPT},
            },
        ]

        updated, changes = module.plan_script_updates(
            tasks,
            module.OLD_SCRIPT,
            module.NEW_SCRIPT,
            target_task_names={"dwd_b"},
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["task_name"], "dwd_b")
        self.assertEqual(updated[0]["taskParams"]["rawScript"], module.OLD_SCRIPT)
        self.assertEqual(updated[1]["taskParams"]["rawScript"], module.NEW_SCRIPT)

    def test_pick_environment_code_by_name(self):
        module = load_module()
        environments = [
            {"name": "bi", "code": 1},
            {"name": "dw_platform", "code": 2},
        ]

        self.assertEqual(module.pick_environment_code(environments, "dw_platform"), 2)

    def test_pick_environment_code_by_name_errors_when_missing(self):
        module = load_module()

        with self.assertRaises(ValueError):
            module.pick_environment_code([{"name": "bi", "code": 1}], "dw_platform")


if __name__ == "__main__":
    unittest.main()
