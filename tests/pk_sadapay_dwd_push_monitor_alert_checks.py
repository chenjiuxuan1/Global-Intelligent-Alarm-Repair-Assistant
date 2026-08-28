import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

from alert.pk_sadapay_dwd_push_monitor_alert import (
    ALERT_TITLE,
    COUNTRY_LABEL,
    DEFAULT_MENTIONS,
    FIELD_PATTERN,
    MENTION_LABEL,
    _call_gateway,
    _extract_total_list,
    _strip_unit,
    find_task_instance,
    find_workflow,
    format_alert_message,
    get_latest_instance,
    parse_datax_summary,
    resolve_project,
)

SAMPLE_DATAX_LOG = """2026-08-28 08:13:09.927 INFO  - 任务启动时刻 : 2026-08-28 11:12:59
2026-08-28 08:13:09.927 INFO  - 任务结束时刻 : 2026-08-28 11:13:09
2026-08-28 08:13:09.927 INFO  - 任务总计耗时 : 10s
2026-08-28 08:13:09.927 INFO  - 任务平均流量 : 86B/s
2026-08-28 08:13:09.927 INFO  - 记录写入速度 : 0rec/s
2026-08-28 08:13:09.927 INFO  - 读出记录总数 : 3
2026-08-28 08:13:09.927 INFO  - 读写失败总数 : 0
2026-08-28 08:13:09.961 INFO  - 任务执行结束
"""


class FakeGatewayResponse:
    """模仿 ds-scheduler 网关 webhook 返回结构。"""

    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"success": True, "data": self._data}).encode("utf-8")

    def getcode(self):
        return 200


class FakeRawResponse:
    """原样返回给定 JSON 对象的响应。"""

    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._data).encode("utf-8")

    def getcode(self):
        return 200


class PkSadapayDwdPushAlertTests(unittest.TestCase):
    # ----- 日志解析 -----
    def test_parse_datax_summary_extracts_all_fields(self):
        summary = parse_datax_summary(SAMPLE_DATAX_LOG)
        self.assertEqual(summary["任务启动时刻"], "2026-08-28 11:12:59")
        self.assertEqual(summary["任务结束时刻"], "2026-08-28 11:13:09")
        self.assertEqual(summary["任务总计耗时"], "10s")
        self.assertEqual(summary["任务平均流量"], "86B/s")
        self.assertEqual(summary["记录写入速度"], "0rec/s")
        self.assertEqual(summary["读出记录总数"], "3")
        self.assertEqual(summary["读写失败总数"], "0")

    def test_field_pattern_matches_log_lines(self):
        matches = FIELD_PATTERN.findall(SAMPLE_DATAX_LOG)
        self.assertEqual(len(matches), 7)

    def test_strip_unit(self):
        self.assertEqual(_strip_unit("3"), 3)
        self.assertEqual(_strip_unit("86B/s"), 86)
        self.assertEqual(_strip_unit("0rec/s"), 0)
        self.assertEqual(_strip_unit(""), 0)
        self.assertEqual(_strip_unit(None), 0)

    # ----- 消息组装 -----
    def test_format_alert_message_matches_required_format(self):
        summary = parse_datax_summary(SAMPLE_DATAX_LOG)
        message = format_alert_message(summary, alert_time="2026-08-28 11:22:22")
        self.assertEqual(
            message,
            "🚨 sadpay推送业务库监控告警\n"
            "集群: 巴基斯坦\n"
            "读出记录总数: 3 条，读写失败总数：0条，\n"
            "告警时间: 2026-08-28 11:22:22\n"
            "@何柳琴",
        )
        self.assertIn(ALERT_TITLE, message)
        self.assertIn(COUNTRY_LABEL, message)
        self.assertIn(MENTION_LABEL, message)

    def test_default_mentions_contain_gretchenhe(self):
        self.assertIn("gretchenhe@kn.group", DEFAULT_MENTIONS)

    # ----- 网关调用 -----
    def test_call_gateway_posts_expected_payload(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeGatewayResponse({"code": 0, "msg": "success", "data": {"totalList": []}})

        with mock.patch.object(
            __import__("urllib.request", fromlist=["urlopen"]), "urlopen", side_effect=fake_urlopen
        ) as urlopen_mock:
            result = _call_gateway(
                "list_workflows",
                {"project_code": 123},
                webhook_url="https://example.test/webhook/ds-scheduler",
                ds_token="tok-123",
            )

        self.assertEqual(captured["url"], "https://example.test/webhook/ds-scheduler")
        self.assertEqual(captured["timeout"], 40)
        self.assertEqual(captured["body"]["country"], "pk")
        self.assertEqual(captured["body"]["action"], "list_workflows")
        self.assertEqual(captured["body"]["ds_token"], "tok-123")
        self.assertEqual(result["code"], 0)

    def test_call_gateway_raises_on_failure_response(self):
        def fake_urlopen(request, timeout=0):
            return FakeRawResponse({"success": False, "message": "boom"})

        with mock.patch.object(
            __import__("urllib.request", fromlist=["urlopen"]), "urlopen", side_effect=fake_urlopen
        ):
            with self.assertRaises(RuntimeError):
                _call_gateway(
                    "list_workflows",
                    {},
                    webhook_url="https://example.test/webhook/ds-scheduler",
                    ds_token="tok-123",
                )

    def test_call_gateway_entry_runs_entry_and_parses_data(self):
        """直连模式：调用 ds_scheduler_entry.py 并解析 stdout JSON 的 data。"""
        captured = {}

        class FakeProc:
            returncode = 0
            stdout = json.dumps(
                {
                    "success": True,
                    "country": "pk",
                    "action": "list_workflows",
                    "request_id": "req-1",
                    "data": {"data": {"totalList": [{"code": 1}]}},
                    "error": None,
                },
                ensure_ascii=False,
            )
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return FakeProc()

        with mock.patch("alert.pk_sadapay_dwd_push_monitor_alert.subprocess.run", side_effect=fake_run):
            result = _call_gateway(
                "list_workflows",
                {"project_code": 123},
                webhook_url="https://example.test/webhook/ds-scheduler",
                ds_token="tok-123",
                gateway_entry="/root/ds-scheduler-gateway/scripts/ds_scheduler_entry.py",
            )

        self.assertIn("/root/ds-scheduler-gateway/scripts/ds_scheduler_entry.py", captured["cmd"])
        self.assertIn("--country", captured["cmd"])
        self.assertIn("pk", captured["cmd"])
        self.assertIn("tok-123", captured["cmd"])
        self.assertTrue(captured["kwargs"]["capture_output"])
        self.assertEqual(result["data"]["totalList"], [{"code": 1}])

    def test_call_gateway_entry_raises_on_failure(self):
        class FakeProcFail:
            returncode = 0
            stdout = json.dumps(
                {"success": False, "country": "pk", "action": "resolve_project",
                 "request_id": "req-2", "data": None,
                 "error": {"code": "DS_API_ERROR", "message": {"status": 401}}},
                ensure_ascii=False,
            )
            stderr = ""

        with mock.patch(
            "alert.pk_sadapay_dwd_push_monitor_alert.subprocess.run",
            return_value=FakeProcFail(),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                _call_gateway(
                    "resolve_project",
                    {"project_name": "sadapay_ftp数据接入"},
                    webhook_url="https://example.test/webhook/ds-scheduler",
                    ds_token="tok-123",
                    gateway_entry="/root/ds-scheduler-gateway/scripts/ds_scheduler_entry.py",
                )
        self.assertIn("DS_API_ERROR", str(ctx.exception))

    # ----- 解析辅助 -----
    def test_extract_total_list_handles_wrapped_shape(self):
        result = {"code": 0, "msg": "success", "data": {"totalList": [{"code": 1}, {"code": 2}]}}
        self.assertEqual(_extract_total_list(result), [{"code": 1}, {"code": 2}])

    def test_extract_total_list_handles_task_list(self):
        result = {"data": {"taskList": [{"id": 5}]}}
        self.assertEqual(_extract_total_list(result), [{"id": 5}])

    # ----- 解析链路（resolve / workflow / instance / task，用 mock 网关） -----
    def test_resolve_project_returns_code(self):
        with mock.patch(
            "alert.pk_sadapay_dwd_push_monitor_alert._call_gateway",
            return_value={"project_code": "177549275623072"},
        ):
            result = resolve_project(
                webhook_url="https://example.test/webhook/ds-scheduler",
                ds_token="tok",
                project_name="sadapay_ftp数据接入",
            )
        self.assertEqual(result["code"], 177549275623072)

    def test_find_workflow_matches_by_name(self):
        fake_data = {"data": {"totalList": [
            {"code": 100, "name": "test"},
            {"code": 179573193891808, "name": "DWD"},
        ]}}
        with mock.patch(
            "alert.pk_sadapay_dwd_push_monitor_alert._call_gateway", return_value=fake_data
        ):
            result = find_workflow(
                webhook_url="https://example.test/webhook/ds-scheduler",
                ds_token="tok",
                project_code=177549275623072,
                workflow_name="DWD",
            )
        self.assertEqual(result["code"], 179573193891808)

    def test_get_latest_instance_picks_latest_start_time(self):
        fake_data = {"data": {"totalList": [
            {
                "id": 2501824,
                "workflowDefinitionCode": 179573193891808,
                "startTime": "2026-08-28 11:01:45",
            },
            {
                "id": 2501908,
                "workflowDefinitionCode": 179573193891808,
                "startTime": "2026-08-28 11:12:58",
            },
        ]}}
        with mock.patch(
            "alert.pk_sadapay_dwd_push_monitor_alert._call_gateway", return_value=fake_data
        ):
            result = get_latest_instance(
                webhook_url="https://example.test/webhook/ds-scheduler",
                ds_token="tok",
                project_code=177549275623072,
                workflow_code=179573193891808,
            )
        self.assertEqual(result["id"], 2501908)

    def test_find_task_instance_matches_push_task(self):
        fake_data = {"data": {"taskList": [
            {"id": 17201039, "name": "dwd_user_sadapay_user_info数据推送", "taskCode": 179573193898976}
        ]}}
        with mock.patch(
            "alert.pk_sadapay_dwd_push_monitor_alert._call_gateway", return_value=fake_data
        ):
            result = find_task_instance(
                webhook_url="https://example.test/webhook/ds-scheduler",
                ds_token="tok",
                project_code=177549275623072,
                instance_id=2501908,
                task_name="dwd_user_sadapay_user_info数据推送",
            )
        self.assertEqual(result["id"], 17201039)

    def test_collect_metrics_end_to_end_with_mocked_gateway(self):
        from alert.pk_sadapay_dwd_push_monitor_alert import collect_metrics

        def fake_call_gateway(action, payload, **kwargs):
            if action == "resolve_project":
                return {"project_code": "177549275623072"}
            if action == "list_workflows":
                return {"data": {"totalList": [{"code": 179573193891808, "name": "DWD"}]}}
            if action == "list_instances":
                return {
                    "data": {
                        "totalList": [
                            {
                                "id": 2501908,
                                "workflowDefinitionCode": 179573193891808,
                                "startTime": "2026-08-28 11:12:58",
                            }
                        ]
                    }
                }
            if action == "list_task_instances":
                return {
                    "data": {
                        "taskList": [
                            {"id": 17201039, "name": "dwd_user_sadapay_user_info数据推送"}
                        ]
                    }
                }
            if action == "get_task_log":
                return {"log": SAMPLE_DATAX_LOG}
            raise AssertionError(f"unexpected action {action}")

        with mock.patch(
            "alert.pk_sadapay_dwd_push_monitor_alert._call_gateway", side_effect=fake_call_gateway
        ):
            metrics = collect_metrics(
                webhook_url="https://example.test/webhook/ds-scheduler",
                ds_token="tok",
            )

        self.assertEqual(metrics["task_instance_id"], 17201039)
        self.assertEqual(metrics["summary"]["读出记录总数"], "3")
        self.assertEqual(metrics["summary"]["读写失败总数"], "0")


if __name__ == "__main__":
    unittest.main()
