import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import ine_ds_failed_auto_retry as retry
from tools import ds_failed_auto_retry as generic_retry


class IneDsFailedAutoRetryChecks(unittest.TestCase):
    def test_normalize_alert_payload_accepts_nested_ds_fields(self):
        raw = {
            "body": {
                "alert": {
                    "projectCode": 158514956085248,
                    "processInstanceId": 99887766,
                    "processDefinitionName": "INE-DWD",
                    "taskName": "dwd_user_order",
                },
                "ds_token": "token-from-alert",
            }
        }

        alert = retry.normalize_alert_payload(raw)

        self.assertEqual(alert["country"], "ine")
        self.assertEqual(alert["project_code"], "158514956085248")
        self.assertEqual(alert["instance_id"], "99887766")
        self.assertEqual(alert["workflow_name"], "INE-DWD")
        self.assertEqual(alert["task_name"], "dwd_user_order")
        self.assertEqual(alert["retry_key"], "ine:158514956085248:99887766")
        self.assertEqual(alert["ds_token"], "token-from-alert")

    def test_normalize_alert_payload_can_parse_text_alarm(self):
        alert = retry.normalize_alert_payload(
            "DS失败告警 projectCode: 123456 processInstanceId: 987654 taskName: ods_x"
        )

        self.assertEqual(alert["project_code"], "123456")
        self.assertEqual(alert["instance_id"], "987654")

    def test_attempt_recording_persists_and_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"

            self.assertEqual(retry.current_attempts(state_file, "ine:1:2"), 0)
            self.assertEqual(retry.record_attempt(state_file, "ine:1:2"), 1)
            self.assertEqual(retry.record_attempt(state_file, "ine:1:2"), 2)
            self.assertEqual(retry.current_attempts(state_file, "ine:1:2"), 2)

            retry.clear_attempts(state_file, "ine:1:2")
            self.assertEqual(retry.current_attempts(state_file, "ine:1:2"), 0)

    def test_auto_retry_recovers_after_first_retry(self):
        calls = []
        tv_messages = []

        def gateway(action, token, payload, request_id):
            calls.append((action, payload["instance_id"], request_id))
            if action == "get_instance":
                return {"ok": True, "stdout": {"success": True, "data": {"state": "SUCCESS"}}}
            return {"ok": True, "stdout": {"success": True}}

        def tv_sender(message):
            tv_messages.append(message)
            return {"success": True, "status_code": 200}

        with tempfile.TemporaryDirectory() as tmp:
            result = retry.auto_retry(
                alert={
                    "project_code": "100",
                    "instance_id": "200",
                    "retry_key": "ine:100:200",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=tv_sender,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "recovered")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual([call[0] for call in calls], ["get_instance", "retry_instance", "get_instance"])
        self.assertEqual(len(tv_messages), 1)
        self.assertIn("目前自动失败重试中，执行次数：1", tv_messages[0])

    def test_auto_retry_sends_tv_after_three_failed_attempts(self):
        tv_messages = []
        sleeps = []

        def gateway(action, token, payload, request_id):
            if action == "get_instance":
                return {"ok": True, "stdout": {"success": True, "data": {"state": "FAILURE"}}}
            return {"ok": True, "stdout": {"success": True}}

        def tv_sender(message):
            tv_messages.append(message)
            return {"success": True, "status_code": 200}

        with tempfile.TemporaryDirectory() as tmp:
            result = retry.auto_retry(
                alert={
                    "project_code": "100",
                    "instance_id": "200",
                    "workflow_name": "INE-DWD",
                    "task_name": "dwd_user_order",
                    "retry_key": "ine:100:200",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=180,
                state_file=Path(tmp) / "state.json",
                sleep=lambda seconds: sleeps.append(seconds),
                gateway_runner=gateway,
                tv_sender=tv_sender,
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "failed_after_max_attempts")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual([seconds for seconds in sleeps if seconds == 180], [180, 180, 180])
        self.assertEqual(len(tv_messages), 4)
        self.assertIn("目前自动失败重试中，执行次数：1", tv_messages[0])
        self.assertIn("目前自动失败重试中，执行次数：2", tv_messages[1])
        self.assertIn("目前自动失败重试中，执行次数：3", tv_messages[2])
        self.assertIn("目前自动失败重试中，执行次数：3", tv_messages[3])
        self.assertIn("当前重试次数已达上限", tv_messages[3])
        self.assertIn("INE-DWD", tv_messages[3])

    def test_payload_b64_cli_shape_is_json_decodable(self):
        raw = {"project_code": "100", "instance_id": "200"}
        encoded = base64.b64encode(json.dumps(raw).encode("utf-8")).decode("ascii")

        self.assertEqual(retry._decode_payload(encoded), raw)

    def test_generic_retry_uses_requested_country_in_alert_and_gateway(self):
        raw = {"project_code": "100", "instance_id": "200"}
        alert = generic_retry.normalize_alert_payload(raw, country="mx")

        self.assertEqual(alert["country"], "mx")
        self.assertEqual(alert["retry_key"], "mx:100:200")
        self.assertTrue(str(generic_retry.default_state_file("mx")).endswith("mx_ds_failed_retry_counts.json"))

    def test_generic_retry_normalizes_id_to_ine(self):
        alert = generic_retry.normalize_alert_payload(
            {"country": "id", "project_code": "100", "instance_id": "200"},
            country="id",
        )

        self.assertEqual(alert["country"], "ine")
        self.assertEqual(alert["retry_key"], "ine:100:200")

    def test_generic_retry_normalizes_ph_ds_alert_array_payload(self):
        raw = [
            {
                "projectCode": 15843450427744,
                "projectName": "菲律宾数仓-正式环境",
                "workflowInstanceId": 2004745,
                "workflowDefinitionCode": 15845044707680,
                "workflowInstanceName": "菲律宾-数仓工作流（1D）-20260715122501017",
                "commandType": "START_FAILURE_TASK_PROCESS",
                "workflowExecutionStatus": "FAILURE",
                "modifyBy": "bigdata",
                "recovery": "NO",
                "runTimes": 2,
                "workflowStartTime": "2026-07-15 12:25:01",
                "workflowEndTime": "2026-07-15 12:49:35",
                "workflowHost": "10.20.10.12:5678",
            }
        ]

        alert = generic_retry.normalize_alert_payload(raw, country="ph")

        self.assertEqual(alert["country"], "ph")
        self.assertEqual(alert["project_code"], "15843450427744")
        self.assertEqual(alert["project_name"], "菲律宾数仓-正式环境")
        self.assertEqual(alert["instance_id"], "2004745")
        self.assertEqual(alert["workflow_definition_code"], "15845044707680")
        self.assertEqual(alert["workflow_name"], "菲律宾-数仓工作流（1D）-20260715122501017")
        self.assertEqual(alert["workflow_execution_status"], "FAILURE")
        self.assertEqual(alert["workflow_start_time"], "2026-07-15 12:25:01")
        self.assertEqual(alert["workflow_end_time"], "2026-07-15 12:49:35")
        self.assertEqual(alert["workflow_host"], "10.20.10.12:5678")
        self.assertEqual(alert["run_times"], "2")
        self.assertEqual(alert["retry_key"], "ph:15843450427744:2004745")

    def test_generic_retry_uses_ph_tv_destination_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = generic_retry.get_country_tv_config("ph")

        self.assertEqual(config["url"], "https://tv-service-alert.kuainiu.chat/alert")
        self.assertEqual(config["bot_id"], "14470d0e-73e2-4411-9306-4cea9a371264")
        self.assertEqual(config["app_id"], "")
        self.assertEqual(config["mentions"], "simontang@kn.group,jiangchuanchen@kn.group")

    def test_generic_retry_country_tv_env_override_wins(self):
        with mock.patch.dict(
            os.environ,
            {
                "DS_FAILED_TV_URL": "https://default.example/alert",
                "DS_FAILED_TV_BOT_ID": "default-bot",
                "DS_FAILED_TV_URL_PH": "https://ph.example/alert",
                "DS_FAILED_TV_BOT_ID_PH": "ph-bot",
                "DS_FAILED_TV_APP_ID_PH": "ph-app",
                "DS_FAILED_TV_MENTIONS_PH": "owner@kn.group",
            },
            clear=True,
        ):
            config = generic_retry.get_country_tv_config("ph")

        self.assertEqual(config["url"], "https://ph.example/alert")
        self.assertEqual(config["bot_id"], "ph-bot")
        self.assertEqual(config["app_id"], "ph-app")
        self.assertEqual(config["mentions"], "owner@kn.group")

    def test_generic_retry_failure_message_keeps_ds_instance_context(self):
        alert = generic_retry.normalize_alert_payload(
            [
                {
                    "projectCode": 15843450427744,
                    "projectName": "菲律宾数仓-正式环境",
                    "workflowInstanceId": 2004745,
                    "workflowDefinitionCode": 15845044707680,
                    "workflowInstanceName": "菲律宾-数仓工作流（1D）-20260715122501017",
                    "workflowStartTime": "2026-07-15 12:25:01",
                    "workflowEndTime": "2026-07-15 12:49:35",
                    "workflowHost": "10.20.10.12:5678",
                    "runTimes": 2,
                }
            ],
            country="ph",
        )

        message = generic_retry.build_failure_message(
            alert,
            3,
            "FAILURE",
            {"stdout": {"success": True, "data": {"state": "FAILURE", "errorMessage": "SQL执行失败"}}},
            "simontang@kn.group,jiangchuanchen@kn.group",
        )

        self.assertIn('"projectName":"菲律宾数仓-正式环境"', message)
        self.assertIn('"workflowInstanceId":2004745', message)
        self.assertIn('"workflowDefinitionCode":15845044707680', message)
        self.assertIn('"workflowInstanceName":"菲律宾-数仓工作流（1D）-20260715122501017"', message)
        self.assertIn('"workflowHost":"10.20.10.12:5678"', message)
        self.assertIn("定时任务执行失败，失败原因：SQL执行失败", message)
        self.assertIn("目前自动失败重试中，执行次数：3", message)
        self.assertIn("当前重试次数已达上限，需要负责人查看处理@simontang@kn.group @jiangchuanchen@kn.group", message)

    def test_generic_retry_progress_message_keeps_raw_array_shape(self):
        alert = generic_retry.normalize_alert_payload(
            [
                {
                    "projectCode": 15843450427744,
                    "projectName": "菲律宾数仓-正式环境",
                    "workflowInstanceId": 2058935,
                    "workflowInstanceName": "菲律宾-数仓工作流（1D）-20260720122501017",
                }
            ],
            country="ph",
        )

        message = generic_retry.build_retry_progress_message(alert, 1, "任务节点失败")

        self.assertTrue(message.startswith('[{"projectCode":15843450427744'))
        self.assertIn("定时任务执行失败，失败原因：任务节点失败", message)
        self.assertIn("目前自动失败重试中，执行次数：1", message)

    def test_generic_retry_reads_failed_task_log_when_instance_has_no_reason(self):
        calls = []
        messages = []

        def gateway(action, token, payload, request_id):
            calls.append(action)
            if action == "get_instance":
                # DolphinScheduler also returns the failure state as numeric code 6.
                return {"ok": True, "stdout": {"success": True, "data": {"state": 6}}}
            if action == "list_task_instances":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {
                            "code": 0,
                            "data": {"totalList": [{"id": 88, "name": "失败SQL", "state": "FAILURE"}]},
                        },
                    },
                }
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {"log": "INFO start\\nERROR Table test_missing_table does not exist\\n"},
                    },
                }
            return {"ok": True, "stdout": {"success": True}}

        with tempfile.TemporaryDirectory() as tmp:
            result = generic_retry.auto_retry(
                alert={"country": "mx", "project_code": "100", "instance_id": "200", "retry_key": "mx:100:200"},
                ds_token="token",
                max_attempts=1,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
            )

        self.assertFalse(result["success"])
        self.assertIn("list_task_instances", calls)
        self.assertIn("get_task_log", calls)
        self.assertIn("ERROR Table test_missing_table does not exist", messages[0])
        self.assertIn("ERROR Table test_missing_table does not exist", messages[-1])

    def test_generic_retry_max_attempt_summary_uses_concise_task_log_root_cause(self):
        messages = []

        def gateway(action, token, payload, request_id):
            if action == "list_task_instances":
                return {
                    "ok": True,
                    "stdout": {"success": True, "data": {"data": {"totalList": [{"id": 88, "state": 6}]}}},
                }
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {
                            "log": "ERROR executor failed\nCaused by: java.sql.SQLSyntaxErrorException: Unknown table test_missing_table\nat stack.frame",
                        },
                    },
                }
            raise AssertionError(f"unexpected action: {action}")

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            generic_retry.record_attempt(state_file, "mx:100:200")
            generic_retry.record_attempt(state_file, "mx:100:200")
            generic_retry.record_attempt(state_file, "mx:100:200")
            result = generic_retry.auto_retry(
                alert={"country": "mx", "project_code": "100", "instance_id": "200", "retry_key": "mx:100:200"},
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=state_file,
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
            )

        self.assertEqual(result["status"], "max_attempts_reached")
        self.assertIn("java.sql.SQLSyntaxErrorException: Unknown table test_missing_table", messages[0])
        self.assertNotIn("at stack.frame", messages[0])

    def test_generic_retry_max_summary_reuses_cached_reason_and_sends_once(self):
        messages = []

        def gateway(action, token, payload, request_id):
            # Simulate a short-lived task-log API failure during the final summary.
            if action == "list_task_instances":
                return {"ok": True, "stdout": {"success": True, "data": {"data": {"totalList": []}}}}
            raise AssertionError(f"unexpected action: {action}")

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            for _ in range(3):
                generic_retry.record_attempt(state_file, "mx:100:200")
            generic_retry.record_failure_context(
                state_file,
                "mx:100:200",
                "java.sql.SQLSyntaxErrorException: Unknown table dm_analyst.missing_table",
                "kuiwu@kn.group",
            )
            result = generic_retry.auto_retry(
                alert={"country": "mx", "project_code": "100", "instance_id": "200", "retry_key": "mx:100:200"},
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=state_file,
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
            )
            repeated = generic_retry.auto_retry(
                alert={"country": "mx", "project_code": "100", "instance_id": "200", "retry_key": "mx:100:200"},
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=state_file,
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
            )

        self.assertEqual(result["status"], "max_attempts_reached")
        self.assertEqual(repeated["status"], "max_attempts_already_notified")
        self.assertEqual(len(messages), 1)
        self.assertIn("Unknown table dm_analyst.missing_table", messages[0])
        self.assertIn("@kuiwu@kn.group", messages[0])

    def test_generic_retry_country_owner_fallback(self):
        with mock.patch.object(generic_retry, "git_task_owner", return_value=""):
            self.assertEqual(generic_retry.resolve_mentions("mx", "任务", ""), "kuiwu@kn.group")
            self.assertEqual(generic_retry.resolve_mentions("cn", "任务", ""), "gretchenhe@kn.group")

    def test_generic_retry_compacts_long_instance_error_message(self):
        long_reason = "\n".join(
            [
                "java.sql.SQLSyntaxErrorException: Unknown table dm_analyst.missing_table",
                "at com.mysql.cj.jdbc.exceptions.SQLError.createSQLException(SQLError.java:121)",
                "2026-07-28 ERROR - executor failed",
                "Caused by: java.sql.SQLSyntaxErrorException: Unknown table dm_analyst.missing_table",
                "at com.mysql.cj.jdbc.exceptions.SQLExceptionsMapping.translateException(SQLExceptionsMapping.java:122)",
            ]
        )

        reason = generic_retry.extract_failure_reason(
            {"stdout": {"success": True, "data": {"state": "FAILURE", "errorMessage": long_reason}}}
        )

        self.assertEqual(reason, "java.sql.SQLSyntaxErrorException: Unknown table dm_analyst.missing_table")


if __name__ == "__main__":
    unittest.main()
