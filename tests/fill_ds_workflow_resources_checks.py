import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "fill_ds_workflow_resources.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fill_ds_workflow_resources", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FillWorkflowResourcesTests(unittest.TestCase):
    def test_build_resource_path_uses_task_name_folder_and_file(self):
        module = load_module()

        path = module.build_resource_path(
            "dwd_w_apply",
            "deploy/resources/starrocks_workflow/dwd",
        )

        self.assertEqual(
            path,
            "dolphinscheduler/resource/deploy/resources/starrocks_workflow/dwd/dwd_w_apply/dwd_w_apply.sql",
        )

    def test_plan_task_updates_only_changes_empty_resource_list(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SQL",
                "taskParams": {"resourceList": [], "sql": "select 1"},
            },
            {
                "name": "dwd_b",
                "code": 2,
                "taskType": "SQL",
                "taskParams": {
                    "resourceList": [{"resourceName": "already.sql"}],
                    "sql": "select 2",
                },
            },
        ]

        updated, changes = module.plan_task_updates(
            tasks,
            "deploy/resources/starrocks_workflow/dwd",
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["task_name"], "dwd_a")
        self.assertEqual(
            updated[0]["taskParams"]["resourceList"],
            [
                {
                    "resourceName": (
                        "dolphinscheduler/resource/deploy/resources/starrocks_workflow/dwd/"
                        "dwd_a/dwd_a.sql"
                    ),
                }
            ],
        )
        self.assertEqual(
            updated[1]["taskParams"]["resourceList"],
            [{"resourceName": "already.sql"}],
        )

    def test_plan_task_updates_can_overwrite_existing_resource_list(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SQL",
                "taskParams": {
                    "resourceList": [{"resourceName": "old/path.sql"}],
                    "sql": "select 1",
                },
            }
        ]

        updated, changes = module.plan_task_updates(
            tasks,
            "deploy/resources/starrocks_workflow/dwd_sec",
            overwrite_existing=True,
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["old_resource_name"], "old/path.sql")
        self.assertEqual(
            updated[0]["taskParams"]["resourceList"],
            [
                {
                    "resourceName": "dolphinscheduler/resource/deploy/resources/starrocks_workflow/dwd_sec/dwd_a/dwd_a.sql"
                }
            ],
        )

    def test_prefix_resource_name_adds_prefix_for_relative_path(self):
        module = load_module()

        prefixed = module.prefix_resource_name(
            "pak_sr/dwd_sql_job/dwd_fox_asset_group_office.sql",
            "dolphinscheduler/resource/dolphinscheduler/resources",
        )

        self.assertEqual(
            prefixed,
            (
                "dolphinscheduler/resource/dolphinscheduler/resources/"
                "pak_sr/dwd_sql_job/dwd_fox_asset_group_office.sql"
            ),
        )

    def test_prefix_resource_name_upgrades_display_path_to_full_name(self):
        module = load_module()

        prefixed = module.prefix_resource_name(
            "dolphinscheduler/resources/pak_sr/sql_job_shell/starrocks_cli.sh",
            "dolphinscheduler/resource/dolphinscheduler/resources",
        )

        self.assertEqual(
            prefixed,
            (
                "dolphinscheduler/resource/dolphinscheduler/resources/"
                "pak_sr/sql_job_shell/starrocks_cli.sh"
            ),
        )

    def test_prefix_resource_name_normalizes_double_prefixed_path(self):
        module = load_module()

        prefixed = module.prefix_resource_name(
            (
                "dolphinscheduler/resource/dolphinscheduler/resources/"
                "dolphinscheduler/resources/pak_sr/sql_job_shell/starrocks_cli.sh"
            ),
            "dolphinscheduler/resource/dolphinscheduler/resources",
        )

        self.assertEqual(
            prefixed,
            (
                "dolphinscheduler/resource/dolphinscheduler/resources/"
                "pak_sr/sql_job_shell/starrocks_cli.sh"
            ),
        )

    def test_plan_task_updates_can_prefix_existing_relative_resource_list(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_fox_user_organization_df",
                "code": 1,
                "taskType": "SHELL",
                "taskParams": {
                    "resourceList": [
                        {"resourceName": "pak_sr/sql_job_shell/starrocks_cli.sh"},
                        {"resourceName": "pak_sr/dwd_sql_job/dwd_fox_user_organization_df.sql"},
                    ],
                    "rawScript": (
                        "bash pak_sr/sql_job_shell/starrocks_cli.sh "
                        "pak_sr/dwd_sql_job/dwd_fox_user_organization_df.sql ${etl_time}"
                    ),
                },
            }
        ]

        updated, changes = module.plan_task_updates(
            tasks,
            "deploy/resources/starrocks_workflow/dwd",
            overwrite_existing=True,
            reuse_existing_relative_paths=True,
            resource_prefix="dolphinscheduler/resource/dolphinscheduler/resources",
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(
            updated[0]["taskParams"]["resourceList"],
            [
                {
                    "resourceName": (
                        "dolphinscheduler/resource/dolphinscheduler/resources/"
                        "pak_sr/sql_job_shell/starrocks_cli.sh"
                    )
                },
                {
                    "resourceName": (
                        "dolphinscheduler/resource/dolphinscheduler/resources/pak_sr/dwd_sql_job/"
                        "dwd_fox_user_organization_df.sql"
                    )
                },
            ],
        )

    def test_plan_task_updates_is_idempotent_for_prefixed_resource_list(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_fox_user_organization_df",
                "code": 1,
                "taskType": "SHELL",
                "taskParams": {
                    "resourceList": [
                        {
                            "resourceName": (
                                "dolphinscheduler/resource/dolphinscheduler/resources/"
                                "pak_sr/sql_job_shell/starrocks_cli.sh"
                            )
                        },
                        {
                            "resourceName": (
                                "dolphinscheduler/resource/dolphinscheduler/resources/pak_sr/dwd_sql_job/"
                                "dwd_fox_user_organization_df.sql"
                            )
                        },
                    ]
                },
            }
        ]

        updated, changes = module.plan_task_updates(
            tasks,
            "deploy/resources/starrocks_workflow/dwd",
            overwrite_existing=True,
            reuse_existing_relative_paths=True,
            resource_prefix="dolphinscheduler/resource/dolphinscheduler/resources",
        )

        self.assertEqual(changes, [])
        self.assertEqual(
            updated[0]["taskParams"]["resourceList"],
            tasks[0]["taskParams"]["resourceList"],
        )

    def test_plan_task_updates_handles_string_task_params(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_c",
                "code": 3,
                "taskType": "SQL",
                "taskParams": '{"resourceList": [], "sql": "select 3"}',
            }
        ]

        updated, changes = module.plan_task_updates(
            tasks,
            "deploy/resources/starrocks_workflow/dwd",
        )

        self.assertEqual(len(changes), 1)
        self.assertIsInstance(updated[0]["taskParams"], dict)
        self.assertEqual(changes[0]["task_code"], "3")

    def test_build_update_payload_serializes_task_and_relation_json(self):
        module = load_module()
        detail = {
            "processDefinition": {
                "code": 1001,
                "name": "DWD",
                "description": "",
                "globalParams": "[]",
                "locations": '[{"taskCode":1,"x":1,"y":2}]',
                "timeout": 0,
                "executionType": "PARALLEL",
                "releaseState": "ONLINE",
                "warningGroupId": 0,
            },
            "taskDefinitionList": [
                {
                    "name": "dwd_a",
                    "code": 1,
                    "version": 2,
                    "description": "",
                    "taskType": "SQL",
                    "taskParams": {"resourceList": []},
                    "flag": "YES",
                    "taskPriority": "MEDIUM",
                    "workerGroup": "default",
                    "failRetryTimes": 0,
                    "failRetryInterval": 1,
                    "timeoutFlag": "CLOSE",
                    "timeoutNotifyStrategy": None,
                    "timeout": 0,
                    "delayTime": 0,
                    "environmentCode": 123,
                    "taskGroupId": 0,
                    "taskGroupPriority": 0,
                    "cpuQuota": -1,
                    "memoryMax": -1,
                    "taskExecuteType": "BATCH",
                    "projectCode": 2001,
                    "userId": 48,
                    "resourceIds": "1,2",
                }
            ],
            "processTaskRelationList": [
                {
                    "name": "",
                    "projectCode": 2001,
                    "processDefinitionCode": 1001,
                    "processDefinitionVersion": 3,
                    "preTaskCode": 0,
                    "preTaskVersion": 0,
                    "postTaskCode": 1,
                    "postTaskVersion": 1,
                    "conditionType": "NONE",
                    "conditionParams": {},
                }
            ],
        }

        payload = module.build_update_payload(detail)

        self.assertEqual(payload["name"], "DWD")
        self.assertIn("taskDefinitionJson", payload)
        self.assertIn("taskRelationJson", payload)
        self.assertEqual(payload["executionType"], "PARALLEL")
        self.assertEqual(payload["releaseState"], "ONLINE")
        self.assertEqual(payload["taskDefinitionJson"][0]["code"], 1)
        self.assertEqual(payload["taskDefinitionJson"][0]["version"], 2)
        self.assertEqual(payload["taskDefinitionJson"][0]["projectCode"], 2001)
        self.assertIsInstance(payload["taskDefinitionJson"][0]["taskParams"], str)
        self.assertIsInstance(payload["taskRelationJson"][0]["conditionParams"], str)
        self.assertEqual(payload["taskRelationJson"][0]["processDefinitionCode"], 1001)
        self.assertEqual(payload["taskRelationJson"][0]["processDefinitionVersion"], 3)

    def test_plan_task_updates_can_target_single_task(self):
        module = load_module()
        tasks = [
            {
                "name": "dwd_a",
                "code": 1,
                "taskType": "SQL",
                "taskParams": {"resourceList": [], "sql": "select 1"},
            },
            {
                "name": "dwd_b",
                "code": 2,
                "taskType": "SQL",
                "taskParams": {"resourceList": [], "sql": "select 2"},
            },
        ]

        updated, changes = module.plan_task_updates(
            tasks,
            "deploy/resources/starrocks_workflow/dwd",
            target_task_names={"dwd_b"},
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["task_name"], "dwd_b")
        self.assertEqual(updated[0]["taskParams"]["resourceList"], [])
        self.assertEqual(
            updated[1]["taskParams"]["resourceList"],
            [{"resourceName": "dolphinscheduler/resource/deploy/resources/starrocks_workflow/dwd/dwd_b/dwd_b.sql"}],
        )

    def test_plan_task_updates_can_use_single_override_resource(self):
        module = load_module()
        tasks = [
            {
                "name": "kbm_summary-30",
                "code": 1,
                "taskType": "SHELL",
                "taskParams": {"resourceList": [], "rawScript": "echo a"},
            },
            {
                "name": "kbm_summary-60",
                "code": 2,
                "taskType": "SHELL",
                "taskParams": {"resourceList": [], "rawScript": "echo b"},
            },
        ]

        updated, changes = module.plan_task_updates(
            tasks,
            "deploy/resources/starrocks_workflow/kbm/kbm_summary",
            overwrite_existing=True,
            resource_name_override=(
                "dolphinscheduler/resource/deploy/resources/starrocks_workflow/"
                "kbm/kbm_summary/kbm_summary.sql"
            ),
        )

        self.assertEqual(len(changes), 2)
        self.assertEqual(
            updated[0]["taskParams"]["resourceList"],
            [
                {
                    "resourceName": (
                        "dolphinscheduler/resource/deploy/resources/starrocks_workflow/"
                        "kbm/kbm_summary/kbm_summary.sql"
                    )
                }
            ],
        )
        self.assertEqual(
            updated[1]["taskParams"]["resourceList"],
            [
                {
                    "resourceName": (
                        "dolphinscheduler/resource/deploy/resources/starrocks_workflow/"
                        "kbm/kbm_summary/kbm_summary.sql"
                    )
                }
            ],
        )

    def test_find_upstream_codes_ignores_root_relation(self):
        module = load_module()
        relations = [
            {"preTaskCode": 0, "postTaskCode": 11},
            {"preTaskCode": 3, "postTaskCode": 11},
            {"preTaskCode": 5, "postTaskCode": 11},
            {"preTaskCode": 8, "postTaskCode": 12},
        ]

        upstream = module.find_upstream_codes("11", relations)

        self.assertEqual(upstream, ["3", "5"])

    def test_build_task_update_payload_serializes_task_params(self):
        module = load_module()
        task = {
            "name": "dwd_a",
            "description": "desc",
            "taskType": "SHELL",
            "taskParams": {"resourceList": [], "rawScript": "echo 1"},
            "flag": "YES",
            "taskPriority": "MEDIUM",
            "workerGroup": "default",
            "environmentCode": 123,
            "failRetryTimes": 0,
            "failRetryInterval": 1,
            "timeout": 0,
            "timeoutFlag": "CLOSE",
            "taskGroupId": 0,
            "taskGroupPriority": 0,
            "cpuQuota": -1,
            "memoryMax": -1,
        }

        payload = module.build_task_update_payload(task, 99)

        self.assertEqual(payload["workflowCode"], 99)
        self.assertIsInstance(payload["taskParams"], str)
        self.assertIn('"rawScript": "echo 1"', payload["taskParams"])


if __name__ == "__main__":
    unittest.main()
