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
    _call_gateway,
    _extract_total_list,
    _strip_unit,
    category_from_file,
    find_task_instance,
    find_workflow,
    format_alert_message,
    get_latest_instance,
    parse_datax_summary,
    parse_ftp_log,
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

SAMPLE_FTP_LOG = """2026-08-28 16:15:43.654 INFO  -  -> [2026-08-28 16:15:43] 远端扫描完成: files=3, cost=0.19 秒
2026-08-28 16:15:43.843 INFO  -  -> [2026-08-28 16:15:43] SFTP 待检查文件数: 3
2026-08-28 16:16:14.394 INFO  -  -> [2026-08-28 16:16:14] 本次运行结束: downloaded=3, processed=3, failed=1
2026-08-28 16:16:14.394 INFO  -  -> [2026-08-28 16:16:14] 文件名称:Account_Aggregates_270826.csv.pgp 文件数据量:10004 入库成功数据量:10004 入库失败数据量:0
2026-08-28 16:16:14.394 INFO  -  -> [2026-08-28 16:16:14] 文件名称:Transactions_270826_part_04.csv.pgp 文件数据量:191895 入库成功数据量:191895 入库失败数据量:0
2026-08-28 16:16:14.394 INFO  -  -> [2026-08-28 16:16:14] 文件名称:User_Identity_270826.csv.pgp 文件数据量:10000 入库成功数据量:0 入库失败数据量:10000
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
            "【SadaPay 数据监控告警】\n"
            "\n"
            "集群：巴基斯坦\n"
            "推送业务库总数: 3 条，读写失败总数：0条\n"
            "\n"
            "告警时间：2026-08-28 11:22:22",
        )
        self.assertIn(ALERT_TITLE, message)
        self.assertIn(COUNTRY_LABEL, message)
        # 正文不再写 @ 文本；真正的 @ 由 TV API 的 mentions 字段触发
        self.assertNotIn("@", message)

    def test_format_alert_message_with_ftp_sections(self):
        summary = parse_datax_summary(SAMPLE_DATAX_LOG)
        ftp = parse_ftp_log(SAMPLE_FTP_LOG)
        message = format_alert_message(summary, ftp=ftp, alert_time="2026-08-28 11:22:22")
        self.assertIn("接收文件：3 个", message)
        self.assertIn("文件类别：3 个", message)
        self.assertIn("失败文件：1 个", message)
        self.assertIn("文件处理明细：", message)
        # 各文件类别汇总行（千分位格式）
        self.assertIn("Account_Aggregates：文件记录 10,004 条｜入库成功 10,004 条｜入库失败 0 条", message)
        self.assertIn("Transactions：文件记录 191,895 条｜入库成功 191,895 条｜入库失败 0 条", message)
        self.assertIn("User_Identity：文件记录 10,000 条｜入库成功 0 条｜入库失败 10,000 条", message)
        # DWD 段仍在
        self.assertIn("推送业务库总数: 3 条，读写失败总数：0条", message)
        self.assertIn("告警时间：2026-08-28 11:22:22", message)

    # ----- ftp2starrocks 日志解析 -----
    def test_parse_ftp_log_extracts_counts_and_categories(self):
        ftp = parse_ftp_log(SAMPLE_FTP_LOG)
        self.assertEqual(ftp["receive_files"], 3)
        self.assertEqual(ftp["failed_files"], 1)
        self.assertEqual(ftp["run_end"], "downloaded=3, processed=3, failed=1")
        self.assertEqual(set(ftp["categories"].keys()), {"Account_Aggregates", "Transactions", "User_Identity"})
        self.assertEqual(ftp["categories"]["Account_Aggregates"]["record_total"], 10004)
        self.assertEqual(ftp["categories"]["Account_Aggregates"]["success"], 10004)
        self.assertEqual(ftp["categories"]["User_Identity"]["failed"], 10000)
        self.assertEqual(len(ftp["files"]), 3)

    def test_category_from_file_variants(self):
        self.assertEqual(category_from_file("Account_Aggregates_270826.csv.pgp"), "Account_Aggregates")
        self.assertEqual(category_from_file("Transactions_270826_part_04.csv.pgp"), "Transactions")
        self.assertEqual(category_from_file("User_Identity_270826.csv.pgp"), "User_Identity")

    def test_parse_ftp_log_empty_log_returns_zeros(self):
        ftp = parse_ftp_log("no relevant lines here")
        self.assertEqual(ftp["receive_files"], 0)
        self.assertEqual(ftp["failed_files"], 0)
        self.assertEqual(ftp["categories"], {})
        self.assertEqual(ftp["run_end"], "")

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

    def test_collect_metrics_falls_back_when_latest_instance_lacks_task(self):
        """最新实例只含校验触发、不含数据推送任务时，回退到最近含数据推送任务的实例。"""
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
                            {"id": 2503781, "workflowDefinitionCode": 179573193891808,
                             "startTime": "2026-08-28 16:36:42"},
                            {"id": 2501908, "workflowDefinitionCode": 179573193891808,
                             "startTime": "2026-08-28 11:12:58"},
                        ]
                    }
                }
            if action == "list_task_instances":
                instance_id = payload.get("instance_id")
                if instance_id == 2503781:
                    return {"data": {"taskList": [
                        {"id": 17214176, "name": "校验触发", "taskType": "SHELL"}
                    ]}}
                return {"data": {"taskList": [
                    {"id": 17201039, "name": "dwd_user_sadapay_user_info数据推送"}
                ]}}
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

        # 应回退到 2501908（含数据推送任务）
        self.assertEqual(metrics["instance"]["id"], 2501908)
        self.assertEqual(metrics["task_instance_id"], 17201039)
        self.assertEqual(metrics["summary"]["读出记录总数"], "3")


if __name__ == "__main__":
    unittest.main()
