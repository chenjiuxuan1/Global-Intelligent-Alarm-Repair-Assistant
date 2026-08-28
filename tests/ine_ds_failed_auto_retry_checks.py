import base64
import json
import multiprocessing
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import ine_ds_failed_auto_retry as retry
from tools import ds_failed_auto_retry as generic_retry


def _record_attempt_worker(state_file, retry_key, start_event):
    start_event.wait()
    generic_retry.record_attempt(Path(state_file), retry_key)


class IneDsFailedAutoRetryChecks(unittest.TestCase):
    class FakeClock:
        def __init__(self):
            self.value = 0.0

        def monotonic(self):
            return self.value

        def sleep(self, seconds):
            self.value += seconds

    class FakeRegistry:
        def __init__(self, register_decision, heartbeat_decisions=None):
            self.register_decision = register_decision
            self.heartbeat_decisions = list(heartbeat_decisions or [])
            self.registered = []
            self.unregistered = []
            self.heartbeats = []

        def register(self, retry_key, *, pid, request_id="", instance_id=""):
            self.registered.append((retry_key, pid, request_id, instance_id))
            return dict(self.register_decision)

        def heartbeat(self, retry_key, *, pid):
            self.heartbeats.append((retry_key, pid))
            if self.heartbeat_decisions:
                return dict(self.heartbeat_decisions.pop(0))
            return {"accepted": True, "circuit_open": False, "active_count": 1}

        def unregister(self, retry_key, *, pid):
            self.unregistered.append((retry_key, pid))
            return {"accepted": True, "circuit_open": False, "active_count": 0}

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
        get_instance_calls = 0

        def gateway(action, token, payload, request_id):
            nonlocal get_instance_calls
            calls.append((action, payload["instance_id"], request_id))
            if action == "get_instance":
                get_instance_calls += 1
                state = "FAILURE" if get_instance_calls == 1 else "SUCCESS"
                return {"ok": True, "stdout": {"success": True, "data": {"state": state}}}
            if action == "list_task_instances":
                # The pre-check lookup runs before the worker log is visible, so
                # it returns an empty list.  By recovery time the failed task is
                # available and the recovery re-lookup surfaces the real reason.
                if "-recovered" in request_id:
                    return {
                        "ok": True,
                        "stdout": {
                            "data": {
                                "data": {
                                    "totalList": [
                                        {"id": 77, "name": "dwd_cn_sync", "state": "FAILURE"}
                                    ]
                                }
                            }
                        },
                    }
                return {"ok": True, "stdout": {"data": {"data": {"totalList": []}}}}
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {
                        "data": {"log": "ERROR - SQLState: 08004 - Connection refused"},
                    },
                }
            return {"ok": True, "stdout": {"success": True}}

        def tv_sender(message):
            tv_messages.append(message)
            return {"success": True, "status_code": 200}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"DS_FAILED_REASON_LOOKUP_ATTEMPTS": "1"},
        ):
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
        self.assertEqual(
            [call[0] for call in calls],
            [
                "get_instance",
                "list_task_instances",
                "retry_instance",
                "get_instance",
                "list_task_instances",
                "get_task_log",
            ],
        )
        self.assertEqual(len(tv_messages), 2)
        self.assertIn("目前自动失败重试中，执行次数：1", tv_messages[0])
        self.assertIn("自动重跑已恢复成功，重跑次数：1", tv_messages[1])
        # The recovery-time re-lookup must surface the real root cause instead
        # of the generic "no reason" fallback.
        self.assertIn("Connection refused", tv_messages[1])
        self.assertNotIn("未从 DS 实例详情中解析到明确失败原因", tv_messages[1])

    def test_auto_retry_does_not_retry_when_precheck_is_already_success(self):
        calls = []
        messages = []

        def gateway(action, token, payload, request_id):
            calls.append(action)
            if action == "get_instance":
                return {"ok": True, "stdout": {"success": True, "data": {"state": "SUCCESS"}}}
            raise AssertionError(f"unexpected action: {action}")

        with tempfile.TemporaryDirectory() as tmp:
            result = generic_retry.auto_retry(
                alert={
                    "country": "ph",
                    "project_code": "100",
                    "instance_id": "200",
                    "retry_key": "ph:100:200",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
            )

        self.assertEqual(result["status"], "recovered")
        self.assertEqual(result["attempts"], 0)
        self.assertEqual(calls, ["get_instance"])
        self.assertIn("重跑次数：0", messages[0])

    def test_auto_retry_monitors_running_precheck_without_duplicate_retry(self):
        clock = self.FakeClock()
        messages = []
        states = iter(["RUNNING_EXECUTION", "SUCCESS"])
        retry_calls = 0

        def gateway(action, token, payload, request_id):
            nonlocal retry_calls
            if action == "get_instance":
                return {
                    "ok": True,
                    "stdout": {"success": True, "data": {"state": next(states)}},
                }
            if action == "retry_instance":
                retry_calls += 1
                return {"ok": True, "stdout": {"success": True}}
            raise AssertionError(f"unexpected action: {action}")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "DS_FAILED_INSTANCE_TIMEOUT_SECONDS": "30",
                "DS_FAILED_MONITOR_INTERVAL_SECONDS": "1",
            },
        ):
            result = generic_retry.auto_retry(
                alert={
                    "country": "ph",
                    "project_code": "100",
                    "instance_id": "200",
                    "retry_key": "ph:100:200",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=clock.sleep,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
                monotonic=clock.monotonic,
            )

        self.assertEqual(result["status"], "recovered")
        self.assertEqual(result["attempts"], 0)
        self.assertEqual(retry_calls, 0)
        self.assertIn("自动重跑后任务仍在运行中", messages[0])
        self.assertIn("自动重跑已恢复成功", messages[-1])

    def test_unknown_after_retry_is_monitored_without_duplicate_retry(self):
        clock = self.FakeClock()
        messages = []
        retry_calls = 0
        get_instance_calls = 0

        def gateway(action, token, payload, request_id):
            nonlocal retry_calls, get_instance_calls
            if action == "retry_instance":
                retry_calls += 1
                return {"ok": True, "stdout": {"success": True}}
            if action == "get_instance":
                get_instance_calls += 1
                states = ["FAILURE", "UNKNOWN", "RUNNING_EXECUTION", "SUCCESS"]
                return {
                    "ok": True,
                    "stdout": {"success": True, "data": {"state": states[get_instance_calls - 1]}},
                }
            if action == "list_task_instances":
                return {"ok": True, "stdout": {"data": {"data": {"totalList": []}}}}
            raise AssertionError(f"unexpected action: {action}")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "DS_FAILED_INSTANCE_TIMEOUT_SECONDS": "30",
                "DS_FAILED_MONITOR_INTERVAL_SECONDS": "1",
                "DS_FAILED_REASON_LOOKUP_ATTEMPTS": "1",
            },
        ):
            result = generic_retry.auto_retry(
                alert={
                    "country": "pk",
                    "project_code": "100",
                    "instance_id": "200",
                    "retry_key": "pk:100:200",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=clock.sleep,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
                monotonic=clock.monotonic,
            )

        self.assertEqual(result["status"], "recovered")
        self.assertEqual(retry_calls, 1)
        self.assertEqual(result["attempts"], 1)
        self.assertIn("自动重跑已恢复成功", messages[-1])

    def test_concurrent_instances_do_not_overwrite_retry_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            start_event = multiprocessing.Event()
            processes = [
                multiprocessing.Process(
                    target=_record_attempt_worker,
                    args=(str(state_file), f"ph:100:{index}", start_event),
                )
                for index in range(20)
            ]
            for process in processes:
                process.start()
            start_event.set()
            for process in processes:
                process.join(timeout=10)

            state = generic_retry._read_json(state_file)

        self.assertTrue(all(process.exitcode == 0 for process in processes))
        self.assertEqual(len(state), 20)
        self.assertTrue(all(item["attempts"] == 1 for item in state.values()))

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
        # Terminal failures must notify on every attempt, not only after all
        # retries exhaust.
        self.assertEqual(len(tv_messages), 4)
        self.assertIn("目前自动失败重试中，执行次数：1", tv_messages[0])
        self.assertIn("目前自动失败重试中，执行次数：2", tv_messages[1])
        self.assertIn("目前自动失败重试中，执行次数：3", tv_messages[2])
        self.assertIn("自动重跑已完成 3 次且全部失败", tv_messages[3])
        self.assertIn("当前状态：FAILURE", tv_messages[3])
        self.assertIn("INE-DWD", tv_messages[3])

    def test_payload_b64_cli_shape_is_json_decodable(self):
        raw = {"project_code": "100", "instance_id": "200"}
        encoded = base64.b64encode(json.dumps(raw).encode("utf-8")).decode("ascii")

        self.assertEqual(retry._decode_payload(encoded), raw)

    def test_gateway_timeout_returns_failed_result_instead_of_crashing_monitor(self):
        with mock.patch.object(
            generic_retry.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["gateway"], timeout=120),
        ):
            result = generic_retry.run_gateway_action(
                "get_instance",
                "token",
                {"project_code": "100", "instance_id": "200"},
                "pk-timeout",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["returncode"], 124)
        self.assertIn("timed out", result["stderr"].lower())

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
        self.assertIn("自动重跑已完成 3 次且全部失败", message)
        self.assertIn("当前状态：FAILURE，需要负责人查看@simontang@kn.group @jiangchuanchen@kn.group", message)

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

    def test_generic_retry_replaces_run_etl_fail_wrapper_with_task_log_root_cause(self):
        messages = []

        def gateway(action, token, payload, request_id):
            if action == "get_instance":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {
                            "state": "FAILURE",
                            "errorMessage": "2026-07-29 console - ERROR - run etl fail",
                        },
                    },
                }
            if action == "list_task_instances":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {"data": {"totalList": [{"id": 88, "name": "dwd_orders", "state": "FAILURE"}]}},
                    },
                }
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {"log": "INFO start\nCaused by: java.sql.SQLSyntaxErrorException: Unknown table dw.dwd_orders\n"},
                    },
                }
            return {"ok": True, "stdout": {"success": True}}

        with tempfile.TemporaryDirectory() as tmp:
            generic_retry.auto_retry(
                alert={"country": "ph", "project_code": "100", "instance_id": "200", "retry_key": "ph:100:200"},
                ds_token="token",
                max_attempts=1,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
            )

        self.assertIn("java.sql.SQLSyntaxErrorException: Unknown table dw.dwd_orders", messages[0])
        self.assertNotIn("run etl fail", messages[0])

    def test_generic_retry_prefers_failed_task_log_and_reports_task_name(self):
        """A process-level error must not prevent task lookup or hide the failed task name."""
        calls = []
        messages = []

        def gateway(action, token, payload, request_id):
            calls.append(action)
            if action == "get_instance":
                if request_id.endswith("-before"):
                    return {
                        "ok": True,
                        "stdout": {
                            "success": True,
                            "data": {
                                "state": "FAILURE",
                                "errorMessage": "1064 (HY000): process-level wrapper error",
                            },
                        },
                    }
                return {"ok": True, "stdout": {"success": True, "data": {"state": "RUNNING_EXECUTION"}}}
            if action == "list_task_instances":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {
                            "data": {
                                "totalList": [
                                    {"id": 8899, "name": "dwd_pk_user_snapshot", "state": "FAILURE"}
                                ]
                            }
                        },
                    },
                }
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {
                            "log": "ERROR - Cannot cast column event_time from TIMESTAMP(0) to STRING NOT NULL"
                        },
                    },
                }
            if action == "retry_instance":
                return {"ok": True, "stdout": {"success": True}}
            raise AssertionError(f"unexpected action: {action}")

        clock = self.FakeClock()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "DS_FAILED_MONITOR_INTERVAL_SECONDS": "60",
                "DS_FAILED_INSTANCE_TIMEOUT_SECONDS": "1800",
            },
        ):
            result = generic_retry.auto_retry(
                alert={
                    "country": "pk",
                    "project_code": "169585666733760",
                    "instance_id": "2367606",
                    "retry_key": "pk:169585666733760:2367606",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=clock.sleep,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
                monotonic=clock.monotonic,
            )

        self.assertEqual(result["status"], "timeout_needs_owner")
        self.assertIn("list_task_instances", calls)
        self.assertIn("get_task_log", calls)
        # The progress notification now fires before the first retry, carrying
        # the located task identity and root cause.
        self.assertIn("目前自动失败重试中，执行次数：1", messages[0])
        self.assertIn("失败任务：dwd_pk_user_snapshot", messages[0])
        self.assertIn("Cannot cast column event_time", messages[0])
        self.assertNotIn("process-level wrapper error", messages[0])
        self.assertIn("原失败任务：dwd_pk_user_snapshot", messages[1])
        self.assertIn("失败任务：dwd_pk_user_snapshot", messages[-1])
        self.assertIn("定时任务 30 分钟内未恢复", messages[-1])
        self.assertIn("实际重跑次数：1", messages[-1])
        self.assertIn("当前状态：RUNNING_EXECUTION", messages[-1])

    def test_generic_retry_final_failure_keeps_cached_task_identity_and_reason(self):
        """A later process wrapper must not replace the task-level failure context."""
        task_list_calls = 0
        messages = []

        def gateway(action, token, payload, request_id):
            nonlocal task_list_calls
            if action == "get_instance":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {"state": "FAILURE", "errorMessage": "process-level wrapper error"},
                    },
                }
            if action == "list_task_instances":
                task_list_calls += 1
                tasks = (
                    [{"id": 8899, "name": "dwd_pk_user_snapshot", "state": "FAILURE"}]
                    if task_list_calls == 1
                    else []
                )
                return {
                    "ok": True,
                    "stdout": {"success": True, "data": {"data": {"totalList": tasks}}},
                }
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {"log": "ERROR - task-level cast failure on event_time"},
                    },
                }
            if action == "retry_instance":
                return {"ok": True, "stdout": {"success": True}}
            raise AssertionError(f"unexpected action: {action}")

        with tempfile.TemporaryDirectory() as tmp:
            result = generic_retry.auto_retry(
                alert={
                    "country": "pk",
                    "project_code": "169585666733760",
                    "instance_id": "2367606",
                    "retry_key": "pk:169585666733760:2367606",
                },
                ds_token="token",
                max_attempts=1,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
            )

        self.assertEqual(result["status"], "failed_after_max_attempts")
        self.assertIn("失败任务：dwd_pk_user_snapshot", messages[-1])
        self.assertIn("task-level cast failure on event_time", messages[-1])
        self.assertNotIn("process-level wrapper error", messages[-1])

    def test_generic_retry_reports_success_after_running_retry_finishes(self):
        """A retry that is initially running must stay monitored and later report recovery."""
        messages = []
        get_instance_calls = 0
        retry_calls = 0

        def gateway(action, token, payload, request_id):
            nonlocal get_instance_calls, retry_calls
            if action == "get_instance":
                get_instance_calls += 1
                states = ["FAILURE", "RUNNING_EXECUTION", "UNKNOWN", "SUCCESS"]
                state = states[min(get_instance_calls - 1, len(states) - 1)]
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {
                            "state": state,
                            "errorMessage": "process-level wrapper error" if state == "FAILURE" else "",
                        },
                    },
                }
            if action == "list_task_instances":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {
                            "data": {
                                "totalList": [
                                    {"id": 8899, "name": "dwd_pk_user_snapshot", "state": "FAILURE"}
                                ]
                            }
                        },
                    },
                }
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {"log": "ERROR - task-level cast failure on event_time"},
                    },
                }
            if action == "retry_instance":
                retry_calls += 1
                return {"ok": True, "stdout": {"success": True}}
            raise AssertionError(f"unexpected action: {action}")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "DS_FAILED_MONITOR_INTERVAL_SECONDS": "0",
                "DS_FAILED_MONITOR_TIMEOUT_SECONDS": "2",
            },
        ):
            result = generic_retry.auto_retry(
                alert={
                    "country": "pk",
                    "project_code": "169585666733760",
                    "instance_id": "2367606",
                    "retry_key": "pk:169585666733760:2367606",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                sleep=lambda _: None,
                gateway_runner=gateway,
                tv_sender=lambda message: messages.append(message) or {"success": True},
            )

        self.assertEqual(result["status"], "recovered")
        self.assertEqual(retry_calls, 1)
        self.assertEqual(len(messages), 3)
        self.assertIn("目前自动失败重试中，执行次数：1", messages[0])
        self.assertIn("自动重跑后任务仍在运行中", messages[1])
        self.assertIn("原失败任务：dwd_pk_user_snapshot", messages[1])
        self.assertIn("自动重跑已恢复成功", messages[2])

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

    def test_country_tenth_active_monitor_opens_circuit_and_alerts_once(self):
        messages = []
        runner_calls = []
        registry = self.FakeRegistry(
            {
                "accepted": False,
                "circuit_open": True,
                "alert_required": True,
                "active_count": 10,
                "circuit_open_until": 2_000_000_000,
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = generic_retry.run_registered_auto_retry(
                alert={
                    "country": "pk",
                    "project_code": "100",
                    "instance_id": "200",
                    "retry_key": "pk:100:200",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                request_id="pk-alert-200",
                registry=registry,
                pid=123,
                tv_sender=lambda message: messages.append(message) or {"success": True},
                auto_retry_runner=lambda **kwargs: runner_calls.append(kwargs) or {"success": True},
            )

        self.assertEqual(result["status"], "country_circuit_open")
        self.assertEqual(runner_calls, [])
        self.assertEqual(len(messages), 1)
        self.assertIn("巴基斯坦", messages[0])
        self.assertIn("实例数已达到 10", messages[0])
        self.assertIn("DolphinScheduler 当前状态不太健康", messages[0])
        self.assertEqual(registry.unregistered, [("pk:100:200", 123)])

    def test_registered_retry_stops_when_country_heartbeat_sees_circuit(self):
        registry = self.FakeRegistry(
            {"accepted": True, "circuit_open": False, "alert_required": False, "active_count": 1},
            [{"accepted": False, "circuit_open": True, "active_count": 10}],
        )
        messages = []

        def runner(**kwargs):
            decision = kwargs["monitor_guard"]()
            self.assertTrue(decision["circuit_open"])
            return {"success": True, "status": "country_circuit_open"}

        with tempfile.TemporaryDirectory() as tmp:
            result = generic_retry.run_registered_auto_retry(
                alert={
                    "country": "ph",
                    "project_code": "100",
                    "instance_id": "200",
                    "retry_key": "ph:100:200",
                },
                ds_token="token",
                max_attempts=3,
                retry_delay_seconds=0,
                state_file=Path(tmp) / "state.json",
                registry=registry,
                pid=456,
                tv_sender=lambda message: messages.append(message) or {"success": True},
                auto_retry_runner=runner,
            )

        self.assertEqual(result["status"], "country_circuit_open")
        self.assertEqual(messages, [])
        self.assertEqual(registry.heartbeats, [("ph:100:200", 456)])
        self.assertEqual(registry.unregistered, [("ph:100:200", 456)])

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

    def test_summarize_skips_run_etl_fail_wrapper(self):
        """The generic 'run etl fail' line must not be surfaced as the reason."""
        log_text = (
            "2026-08-03 18:25:20.000 INFO  -  -> welcome info\n"
            "2026-08-03 18:25:25.000 INFO  -  -> 2026-08-03 18:25:25,000 - console - "
            "ERROR - java.sql.SQLSyntaxErrorException: Unknown table dw.dwd_order\n"
            "2026-08-03 18:25:27.026 INFO  -  -> 2026-08-03 18:25:27,026 - console - "
            "ERROR - run etl fail"
        )
        reason = generic_retry._summarize_task_log(log_text)
        self.assertIn("Unknown table dw.dwd_order", reason)
        self.assertNotIn("run etl fail", reason)

    def test_summarize_strips_ds_prefix_from_error_line(self):
        """DS worker-log prefix should be stripped for a clean alert message."""
        log_text = (
            "2026-08-03 18:25:25.000 INFO  -  -> 2026-08-03 18:25:25,000 - console - "
            "ERROR - Connection refused: connect"
        )
        reason = generic_retry._summarize_task_log(log_text)
        self.assertNotIn("INFO  -  ->", reason)
        self.assertIn("Connection refused", reason)

    def test_summarize_does_not_treat_truncated_sql_tail_as_failure_reason(self):
        """A log page ending inside SQL must not report its last SQL line as the error."""
        log_text = (
            "2026-08-11 11:04:00.000 INFO  -  -> SELECT\n"
            "2026-08-11 11:04:00.001 INFO  -  -> user_id,\n"
            "2026-08-11 11:04:00.002 INFO  -  -> MAX(IF(d0_amount > 0, 1, 0)) AS is_od_user,"
        )

        reason = generic_retry._summarize_task_log(log_text)

        self.assertEqual(reason, "")

    def test_summarize_does_not_treat_sql_error_identifier_as_log_level(self):
        """The word error inside SQL is not an explicit ERROR log record."""
        log_text = "SELECT error AS error_reason FROM task_result"

        reason = generic_retry._summarize_task_log(log_text)

        self.assertEqual(reason, "")

    def test_summarize_detects_kill_statement_without_error_level(self):
        """A SQL killed by a KILL statement at INFO level must still surface."""
        log_text = (
            "2026-08-13 07:26:54,566 - console - INFO - task start\n"
            "2026-08-13 07:26:54,570 - console - INFO - 5025 (HY000): killed by kill statement : "
            "KILL QUERY '4b2768d7-96a5-11f1-aabe-fa163ed414eb'\n"
            "2026-08-13 07:26:54,581 - console - ERROR - run etl fail"
        )
        reason = generic_retry._summarize_task_log(log_text)
        self.assertIn("killed by kill statement", reason)
        self.assertIn("KILL QUERY", reason)

    def test_summarize_detects_access_denied_without_error_level(self):
        """Access-denied DB errors carry no error/exception keyword but are real causes."""
        log_text = (
            "2026-08-03 18:25:20.000 INFO  -  -> Access denied; you need (at least one of) "
            "the SELECT privilege(s) for this operation"
        )
        reason = generic_retry._summarize_task_log(log_text)
        self.assertIn("Access denied", reason)
        self.assertIn("SELECT privilege", reason)

    def test_fetch_failure_info_pages_until_failed_task_found(self):
        """Large workflows can put the failed task beyond the first page."""
        pages = iter(
            [
                {"totalList": [{"id": 10, "name": "早先成功任务", "state": "SUCCESS"}]},
                {"totalList": [{"id": 20, "name": "失败任务", "state": "FAILURE"}]},
                {"totalList": []},
            ]
        )
        page_nos = []

        def gateway(action, token, payload, request_id):
            if action == "list_task_instances":
                page_nos.append(payload["page_no"])
                return {"ok": True, "stdout": {"data": {"data": next(pages)}}}
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {"data": {"log": "ERROR - SQLState: 42000 - syntax error"}},
                }
            raise AssertionError(f"unexpected action: {action}")

        reason, task_name = generic_retry.fetch_failure_info_from_task_log(
            {"project_code": "158515082283008", "instance_id": "1722399"},
            "token",
            "cn-pages",
            gateway,
        )

        self.assertEqual(task_name, "失败任务")
        self.assertIn("SQLState", reason)
        self.assertEqual(page_nos, [1, 2])

    def test_fetch_failure_info_stops_after_empty_page(self):
        """An empty first page means the list is empty; no extra pages are requested."""
        calls = []

        def gateway(action, token, payload, request_id):
            calls.append(action)
            if action == "list_task_instances":
                return {"ok": True, "stdout": {"data": {"data": {"totalList": []}}}}
            raise AssertionError(f"unexpected action: {action}")

        reason, task_name = generic_retry.fetch_failure_info_from_task_log(
            {"project_code": "100", "instance_id": "200"},
            "token",
            "empty-pages",
            gateway,
        )

        self.assertEqual(reason, "")
        self.assertEqual(task_name, "")
        self.assertEqual(calls, ["list_task_instances"])

    def test_fetch_failure_info_falls_back_to_latest_task_log_when_no_failed_state(self):
        """When no task classifies as failed, the most recent task log is still tried."""
        def gateway(action, token, payload, request_id):
            if action == "list_task_instances":
                return {
                    "ok": True,
                    "stdout": {
                        "data": {
                            "data": {
                                "totalList": [
                                    {"id": 100, "name": "早先任务", "state": "SUCCESS"},
                                    {"id": 200, "name": "最新任务", "state": "SUCCESS"},
                                ]
                            }
                        }
                    },
                }
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {
                        "data": {"log": "ERROR - 5025 (HY000): killed by kill statement : KILL QUERY 'x'"},
                    },
                }
            raise AssertionError(f"unexpected action: {action}")

        reason, task_name = generic_retry.fetch_failure_info_from_task_log(
            {"project_code": "12739141488160", "instance_id": "4117583"},
            "token",
            "ine-latest-fallback",
            gateway,
        )

        self.assertEqual(task_name, "最新任务")
        self.assertIn("killed by kill statement", reason)

    def test_summarize_extracts_nonzero_exit_value_without_error_log_level(self):
        log_text = (
            "2026-08-28 05:42:20.000 INFO  -  -> command completed\n"
            "2026-08-28 05:42:21.000 INFO  -  -> Process exited with exit value 127"
        )

        reason = generic_retry._summarize_task_log(log_text)

        self.assertEqual(reason, "Process exited with exit value 127")

    def test_summarize_extracts_sqlstate_without_error_log_level(self):
        log_text = "2026-08-28 05:42:21.000 INFO  -  -> 1064 (HY000): table does not exist"

        reason = generic_retry._summarize_task_log(log_text)

        self.assertEqual(reason, "1064 (HY000): table does not exist")

    def test_failed_task_log_requests_enough_lines_to_reach_trailing_error(self):
        """The fallback log/detail request must not stop at the first 2,000 SQL lines."""
        seen_limits = []

        def gateway(action, token, payload, request_id):
            if action == "list_task_instances":
                return {
                    "ok": True,
                    "stdout": {
                        "success": True,
                        "data": {"data": {"totalList": [{"id": 88, "name": "失败SQL", "state": "FAILURE"}]}},
                    },
                }
            if action == "get_task_log":
                seen_limits.append(payload["limit"])
                if payload["limit"] <= 2000:
                    log = "SELECT\nMAX(IF(d0_amount > 0, 1, 0)) AS is_od_user,"
                else:
                    log = "SELECT\nMAX(IF(d0_amount > 0, 1, 0)) AS is_od_user,\nERROR - Column d0_amount not found"
                return {"ok": True, "stdout": {"success": True, "data": {"log": log}}}
            raise AssertionError(f"unexpected action: {action}")

        reason, task_name = generic_retry.fetch_failure_info_from_task_log(
            {"project_code": "15843450427744", "instance_id": "2321573"},
            "token",
            "ph-test",
            gateway,
        )

        self.assertGreater(seen_limits[0], 2000)
        self.assertEqual(reason, "ERROR - Column d0_amount not found")
        self.assertEqual(task_name, "失败SQL")

    def test_failed_task_lookup_prefers_latest_failed_task_instance(self):
        def gateway(action, token, payload, request_id):
            if action == "list_task_instances":
                return {
                    "ok": True,
                    "stdout": {
                        "data": {
                            "data": {
                                "totalList": [
                                    {"id": 100, "name": "旧失败任务", "state": "FAILURE"},
                                    {"id": 200, "name": "最新失败任务", "state": "FAILURE"},
                                ]
                            }
                        }
                    },
                }
            if action == "get_task_log":
                return {
                    "ok": True,
                    "stdout": {"data": {"log": f"ERROR - task instance {payload['task_instance_id']} failed"}},
                }
            raise AssertionError(f"unexpected action: {action}")

        reason, task_name = generic_retry.fetch_failure_info_from_task_log(
            {"project_code": "100", "instance_id": "200"},
            "token",
            "pk-latest-task",
            gateway,
        )

        self.assertEqual(task_name, "最新失败任务")
        self.assertIn("task instance 200 failed", reason)

    def test_extract_task_log_reason_filters_wrapper_only_log(self):
        """Wrapper-only logs must say the task omitted its underlying exception."""
        log_text = (
            "2026-08-03 18:25:20.000 INFO  -  -> starting etl\n"
            "2026-08-03 18:25:27.026 INFO  -  -> 2026-08-03 18:25:27,026 - console - "
            "ERROR - run etl fail"
        )
        response = {"stdout": {"success": True, "data": {"log": log_text}}}
        reason = generic_retry.extract_task_log_failure_reason(response)
        self.assertEqual(reason, "任务日志仅记录通用失败标记，任务脚本未输出底层异常")

    def test_extract_task_log_reason_finds_real_error_before_wrapper(self):
        """Full gateway response: real error must win over the 'run etl fail' wrapper."""
        log_text = (
            "2026-08-03 18:25:20.000 INFO  -  -> starting etl\n"
            "2026-08-03 18:25:22.000 INFO  -  -> 2026-08-03 18:25:22,000 - console - "
            "ERROR - NullPointerException: cannot invoke method on null object\n"
            "2026-08-03 18:25:27.026 INFO  -  -> 2026-08-03 18:25:27,026 - console - "
            "ERROR - run etl fail"
        )
        response = {
            "stdout": {
                "success": True,
                "data": {
                    "log": log_text,
                    "task_name": "dwd_user_order",
                    "raw_result": {"data": {"content": log_text}},
                },
            }
        }
        reason = generic_retry.extract_task_log_failure_reason(response)
        self.assertIn("NullPointerException", reason)
        self.assertNotIn("run etl fail", reason)


if __name__ == "__main__":
    unittest.main()
