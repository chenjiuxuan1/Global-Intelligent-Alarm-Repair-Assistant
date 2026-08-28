#!/usr/bin/env python3
"""
巴基斯坦 sadapay DWD 数据推送任务日志监控告警。

扫描巴基斯坦 DolphinScheduler 的 `sadapay_ftp数据接入` 项目下 `DWD` 工作流
最新一次调度实例中 `dwd_user_sadapay_user_info数据推送` 数据推送任务节点的
运行日志（DataX JobContainer 统计块），解析以下字段并发送 TV 告警：

- 任务启动时刻
- 任务结束时刻
- 任务总计耗时
- 任务平均流量
- 记录写入速度
- 读出记录总数
- 读写失败总数

消息格式（与需求一致）：
    🚨 sadpay推送业务库监控告警
    集群: 巴基斯坦
    读出记录总数: xxx 条，读写失败总数：xx条，
    告警时间: 2026-08-28 11:22:22

真正的 @ 提醒由 TV API 的 mentions 字段触发（默认 gretchenhe@kn.group = 何柳琴），
消息正文不再重复写 @ 文本。

DS 访问方式（两种，二选一）：
- webhook 模式：通过 n8n ds-scheduler 网关 webhook（country=pk）调用 DolphinScheduler REST API
- 直连模式：在本机（跳板机）直接调用 ds-scheduler-gateway 本地入口
  （--gateway-entry，默认 /root/ds-scheduler-gateway/scripts/ds_scheduler_entry.py）
  当公网 webhook 域名从跳板机访问被 WAF 拦截时，应使用直连模式。

用法：
    python3 alert/pk_sadapay_dwd_push_monitor_alert.py [--dry-run] \
        [--ds-token <token>] [--webhook-url <url>] [--gateway-entry <path>] \
        [--bot-id <id>] [--mentions <a@b.com,c@d.com>]

依赖：Python3 标准库（urllib/json/re/subprocess）+ 平台 core/send_tv_report.py。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# 常量（巴基斯坦 sadapay_ftp 数据接入项目）
# ---------------------------------------------------------------------------
COUNTRY = "pk"
COUNTRY_LABEL = "巴基斯坦"
SOURCE = "pk_sadapay_dwd_alert"

DEFAULT_WEBHOOK_URL = "https://sql-cn.kuainiujinke.com/webhook/ds-scheduler"
# 跳板机直连模式：调用 ds-scheduler-gateway 的本地入口（与 ds-scheduler-router 同架构）
DEFAULT_GATEWAY_ENTRY = "/root/ds-scheduler-gateway/scripts/ds_scheduler_entry.py"

# 项目 / 工作流 / 任务（按名称解析，运行时可覆盖为 code）
DEFAULT_PROJECT_NAME = "sadapay_ftp数据接入"
DEFAULT_WORKFLOW_NAME = "DWD"
DEFAULT_TASK_NAME = "dwd_user_sadapay_user_info数据推送"

# 解析字段
LOG_FIELD_NAMES = [
    "任务启动时刻",
    "任务结束时刻",
    "任务总计耗时",
    "任务平均流量",
    "记录写入速度",
    "读出记录总数",
    "读写失败总数",
]
FIELD_PATTERN = re.compile(r"(任务启动时刻|任务结束时刻|任务总计耗时|任务平均流量|记录写入速度|读出记录总数|读写失败总数)\s*[:：]\s*([^\r\n]*)")

# 告警消息
ALERT_TITLE = "🚨 sadpay推送业务库监控告警"

# 何柳琴 = gretchenhe@kn.group（真正的 @ 由 TV API mentions 字段触发）
DEFAULT_MENTIONS = ["gretchenhe@kn.group"]
# PL 告警测试群机器人（与现有 PL 告警共用）
DEFAULT_BOT_ID = "4d0bcc9b-71bf-41c5-ba9f-89b7278f9214"


# ---------------------------------------------------------------------------
# DS 网关 webhook 调用
# ---------------------------------------------------------------------------
def _call_gateway(
    action: str,
    payload: Dict[str, Any],
    *,
    webhook_url: str,
    ds_token: str,
    country: str = COUNTRY,
    timeout: int = 40,
    gateway_entry: Optional[str] = None,
) -> Dict[str, Any]:
    """调用 ds-scheduler 网关并返回其 data 字段（已解析）。

    两种模式：
    - webhook 模式：POST 到 ds-scheduler 网关 webhook
    - 直连模式（gateway_entry 非空）：在本机直接运行
      ds-scheduler-gateway 的入口脚本（payload-b64 -> stdout JSON），
      与 ds-scheduler-router n8n 节点同架构，适合跳板机运行。
    """
    request_id = f"{SOURCE}-{int(time.time() * 1000)}"
    if gateway_entry:
        return _call_gateway_entry(
            action, payload, entry=gateway_entry, ds_token=ds_token,
            country=country, request_id=request_id, timeout=timeout,
        )
    body = {
        "source": SOURCE,
        "country": country,
        "action": action,
        "ds_token": ds_token,
        "request_id": request_id,
        "payload": payload,
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        if exc.fp is not None:
            try:
                detail = exc.fp.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
        raise RuntimeError(
            f"网关 {action} HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网关 {action} 网络错误: {exc.reason}") from exc

    if not isinstance(result, dict) or not result.get("success"):
        msg = result.get("message") or result.get("msg") or str(result)
        raise RuntimeError(f"网关 {action} 返回失败: {msg}")
    return result.get("data") or {}


def _call_gateway_entry(
    action: str,
    payload: Dict[str, Any],
    *,
    entry: str,
    ds_token: str,
    country: str,
    request_id: str,
    timeout: int = 40,
) -> Dict[str, Any]:
    """直连模式：运行 ds-scheduler-gateway 入口脚本并解析 stdout JSON。"""
    payload_b64 = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    cmd = [
        sys.executable,
        entry,
        "--country", country,
        "--action", action,
        "--ds-token", ds_token,
        "--request-id", request_id,
        "--payload-b64", payload_b64,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"网关 {action} 直连超时") from exc
    except OSError as exc:
        raise RuntimeError(f"网关 {action} 无法运行入口 {entry}: {exc}") from exc

    if proc.returncode != 0:
        raise RuntimeError(
            f"网关 {action} 直连退出码 {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"网关 {action} 直连输出非 JSON: {proc.stdout[:300]}"
        ) from exc
    if not isinstance(result, dict) or not result.get("success"):
        error = result.get("error") or {}
        msg = ""
        if isinstance(error, dict):
            msg = json.dumps(error, ensure_ascii=False)
        elif error:
            msg = str(error)
        raise RuntimeError(f"网关 {action} 返回失败: {msg or result}")
    return result.get("data") or {}


def _extract_total_list(result: Any) -> List[Dict[str, Any]]:
    """兼容 DS 网关多种返回结构，提取 totalList / taskList 等列表。"""
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("totalList", "records", "taskList", "task_list", "items", "list"):
                items = data.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_log_text(result: Dict[str, Any]) -> str:
    """从 get_task_log 返回的 data 中提取日志文本。"""
    if isinstance(result, dict):
        log = result.get("log")
        if isinstance(log, str):
            return log
    return ""


def resolve_project(
    *,
    webhook_url: str,
    ds_token: str,
    project_name: str = DEFAULT_PROJECT_NAME,
    project_code: Optional[int] = None,
    gateway_entry: Optional[str] = None,
) -> Dict[str, Any]:
    if project_code:
        return {"code": project_code, "name": project_name}
    data = _call_gateway(
        "resolve_project",
        {"project_name": project_name},
        webhook_url=webhook_url,
        ds_token=ds_token,
        gateway_entry=gateway_entry,
    )
    code = _safe_int(
        data.get("project_code") or data.get("code") or data.get("project", {}).get("code")
    )
    if not code:
        raise RuntimeError(f"无法解析项目 {project_name!r}")
    return {"code": code, "name": project_name}


def find_workflow(
    *,
    webhook_url: str,
    ds_token: str,
    project_code: int,
    workflow_name: str = DEFAULT_WORKFLOW_NAME,
    workflow_code: Optional[int] = None,
    gateway_entry: Optional[str] = None,
) -> Dict[str, Any]:
    if workflow_code:
        return {"code": workflow_code, "name": workflow_name}
    data = _call_gateway(
        "list_workflows",
        {"project_code": project_code, "page_no": 1, "page_size": 100, "search_val": ""},
        webhook_url=webhook_url,
        ds_token=ds_token,
        gateway_entry=gateway_entry,
    )
    for item in _extract_total_list(data):
        if str(item.get("name") or "").strip() == workflow_name:
            return {"code": _safe_int(item.get("code")), "name": workflow_name}
    raise RuntimeError(f"项目 {project_code} 中未找到工作流 {workflow_name!r}")


def get_latest_instance(
    *,
    webhook_url: str,
    ds_token: str,
    project_code: int,
    workflow_code: int,
    gateway_entry: Optional[str] = None,
) -> Dict[str, Any]:
    data = _call_gateway(
        "list_instances",
        {"project_code": project_code, "page_no": 1, "page_size": 100, "search_val": ""},
        webhook_url=webhook_url,
        ds_token=ds_token,
        gateway_entry=gateway_entry,
    )
    candidates = [
        item
        for item in _extract_total_list(data)
        if _safe_int(item.get("workflowDefinitionCode") or item.get("processDefinitionCode"))
        == workflow_code
    ]
    if not candidates:
        raise RuntimeError(f"工作流 {workflow_code} 暂无调度实例")
    candidates.sort(
        key=lambda item: (
            str(item.get("startTime") or ""),
            _safe_int(item.get("id")),
        )
    )
    return candidates[-1]


def find_latest_instance_with_task(
    *,
    webhook_url: str,
    ds_token: str,
    project_code: int,
    workflow_code: int,
    task_name: str = DEFAULT_TASK_NAME,
    task_code: Optional[int] = None,
    gateway_entry: Optional[str] = None,
    max_instances: int = 20,
) -> Dict[str, Any]:
    """从最新实例往前遍历，找到最近一个包含目标任务的实例及其任务。

    某些调度（如工作流改版后）最新实例可能只含部分任务（例如“校验触发”），
    不包含我们要监控的数据推送任务。此时回退到最近一个包含目标任务的成功实例，
    保证监控始终读到数据推送任务的日志统计。
    """
    data = _call_gateway(
        "list_instances",
        {"project_code": project_code, "page_no": 1, "page_size": max_instances, "search_val": ""},
        webhook_url=webhook_url,
        ds_token=ds_token,
        gateway_entry=gateway_entry,
    )
    candidates = [
        item
        for item in _extract_total_list(data)
        if _safe_int(item.get("workflowDefinitionCode") or item.get("processDefinitionCode"))
        == workflow_code
    ]
    candidates.sort(
        key=lambda item: (
            str(item.get("startTime") or ""),
            _safe_int(item.get("id")),
        ),
        reverse=True,
    )
    for instance in candidates:
        instance_id = _safe_int(instance.get("id"))
        try:
            task = find_task_instance(
                webhook_url=webhook_url,
                ds_token=ds_token,
                project_code=project_code,
                instance_id=instance_id,
                task_name=task_name,
                task_code=task_code,
                gateway_entry=gateway_entry,
            )
        except RuntimeError:
            continue
        return {"instance": instance, "task": task}
    raise RuntimeError(
        f"工作流 {workflow_code} 最近 {max_instances} 次实例中均未找到任务 {task_name!r}"
    )


def find_task_instance(
    *,
    webhook_url: str,
    ds_token: str,
    project_code: int,
    instance_id: int,
    task_name: str = DEFAULT_TASK_NAME,
    task_code: Optional[int] = None,
    gateway_entry: Optional[str] = None,
) -> Dict[str, Any]:
    data = _call_gateway(
        "list_task_instances",
        {
            "project_code": project_code,
            "instance_id": instance_id,
            "page_no": 1,
            "page_size": 100,
            "search_val": "",
        },
        webhook_url=webhook_url,
        ds_token=ds_token,
        gateway_entry=gateway_entry,
    )
    for item in _extract_total_list(data):
        item_name = str(item.get("name") or item.get("taskName") or "").strip()
        item_code = _safe_int(item.get("taskCode"))
        if task_code and item_code == task_code:
            return item
        if task_name and item_name == task_name:
            return item
    raise RuntimeError(f"实例 {instance_id} 中未找到任务 {task_name!r}")


def fetch_task_log(
    *,
    webhook_url: str,
    ds_token: str,
    project_code: int,
    task_instance_id: int,
    gateway_entry: Optional[str] = None,
) -> str:
    data = _call_gateway(
        "get_task_log",
        {"project_code": project_code, "task_instance_id": task_instance_id},
        webhook_url=webhook_url,
        ds_token=ds_token,
        gateway_entry=gateway_entry,
    )
    log = _extract_log_text(data)
    if not log:
        raise RuntimeError(f"任务实例 {task_instance_id} 日志为空")
    return log


# ---------------------------------------------------------------------------
# 日志解析
# ---------------------------------------------------------------------------
def parse_datax_summary(log_text: str) -> Dict[str, str]:
    """从 DataX JobContainer 统计块提取字段（保持原始字符串）。"""
    result: Dict[str, str] = {}
    for match in FIELD_PATTERN.finditer(log_text):
        result[match.group(1)] = match.group(2).strip()
    return result


def _strip_unit(value: str) -> int:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else 0


# ---------------------------------------------------------------------------
# 消息组装 / TV 发送
# ---------------------------------------------------------------------------
def format_alert_message(
    summary: Dict[str, str],
    alert_time: Optional[str] = None,
    cluster_label: str = COUNTRY_LABEL,
    title: str = ALERT_TITLE,
) -> str:
    now = alert_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    read_total = _strip_unit(summary.get("读出记录总数"))
    write_failed = _strip_unit(summary.get("读写失败总数"))
    lines = [
        title,
        f"集群: {cluster_label}",
        f"读出记录总数: {read_total} 条，读写失败总数：{write_failed}条，",
        f"告警时间: {now}",
    ]
    return "\n".join(lines)


def send_to_tv(
    message: str,
    mentions: Optional[List[str]] = None,
    bot_id: Optional[str] = None,
) -> Dict[str, Any]:
    from core.send_tv_report import send_tv_report

    if mentions is None:
        mentions = DEFAULT_MENTIONS
    return send_tv_report(message, mentions=mentions, bot_id=bot_id or DEFAULT_BOT_ID)


def collect_metrics(
    *,
    webhook_url: str,
    ds_token: str,
    project_name: str = DEFAULT_PROJECT_NAME,
    project_code: Optional[int] = None,
    workflow_name: str = DEFAULT_WORKFLOW_NAME,
    workflow_code: Optional[int] = None,
    task_name: str = DEFAULT_TASK_NAME,
    task_code: Optional[int] = None,
    gateway_entry: Optional[str] = None,
) -> Dict[str, Any]:
    """拉取最新任务日志并解析统计字段，返回上下文（含 summary / instance / task）。"""
    project = resolve_project(
        webhook_url=webhook_url,
        ds_token=ds_token,
        project_name=project_name,
        project_code=project_code,
        gateway_entry=gateway_entry,
    )
    project_code = project["code"]

    workflow = find_workflow(
        webhook_url=webhook_url,
        ds_token=ds_token,
        project_code=project_code,
        workflow_name=workflow_name,
        workflow_code=workflow_code,
        gateway_entry=gateway_entry,
    )
    workflow_code = workflow["code"]

    found = find_latest_instance_with_task(
        webhook_url=webhook_url,
        ds_token=ds_token,
        project_code=project_code,
        workflow_code=workflow_code,
        task_name=task_name,
        task_code=task_code,
        gateway_entry=gateway_entry,
    )
    instance = found["instance"]
    task = found["task"]
    instance_id = _safe_int(instance.get("id"))
    task_instance_id = _safe_int(task.get("id") or task.get("taskInstanceId"))

    log_text = fetch_task_log(
        webhook_url=webhook_url,
        ds_token=ds_token,
        project_code=project_code,
        task_instance_id=task_instance_id,
        gateway_entry=gateway_entry,
    )
    summary = parse_datax_summary(log_text)
    return {
        "project_code": project_code,
        "workflow_code": workflow_code,
        "instance": instance,
        "task": task,
        "task_instance_id": task_instance_id,
        "log_text": log_text,
        "summary": summary,
    }


def run(
    *,
    webhook_url: str,
    ds_token: str,
    dry_run: bool = False,
    mentions: Optional[List[str]] = None,
    bot_id: Optional[str] = None,
    project_name: str = DEFAULT_PROJECT_NAME,
    project_code: Optional[int] = None,
    workflow_name: str = DEFAULT_WORKFLOW_NAME,
    workflow_code: Optional[int] = None,
    task_name: str = DEFAULT_TASK_NAME,
    task_code: Optional[int] = None,
    alert_time: Optional[str] = None,
    gateway_entry: Optional[str] = None,
) -> Dict[str, Any]:
    metrics = collect_metrics(
        webhook_url=webhook_url,
        ds_token=ds_token,
        project_name=project_name,
        project_code=project_code,
        workflow_name=workflow_name,
        workflow_code=workflow_code,
        task_name=task_name,
        task_code=task_code,
        gateway_entry=gateway_entry,
    )
    message = format_alert_message(metrics["summary"], alert_time=alert_time)
    if not message.endswith("\n"):
        message = f"{message}\n"

    if dry_run:
        print(message)
        return {"success": True, "status_code": None, "response": "dry_run", "metrics": metrics}

    result = send_to_tv(message, mentions=mentions, bot_id=bot_id)
    if result.get("success"):
        print(f"✅ TV告警发送成功 (HTTP {result.get('status_code')})")
    else:
        print(f"❌ TV告警发送失败 (HTTP {result.get('status_code')})")
        print(result.get("response"))
    return result


def _env_token() -> str:
    for name in ("DS_API_TOKEN_PK", "PK_DS_TOKEN", "DS_TOKEN"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _env_webhook() -> str:
    return (os.environ.get("DS_SCHEDULER_WEBHOOK_URL") or DEFAULT_WEBHOOK_URL).strip()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="巴基斯坦 sadapay DWD 数据推送任务日志监控告警"
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印消息，不发送 TV")
    parser.add_argument(
        "--webhook-url",
        default=None,
        help="ds-scheduler 网关 webhook URL（默认读 DS_SCHEDULER_WEBHOOK_URL 环境变量）",
    )
    parser.add_argument(
        "--gateway-entry",
        default=None,
        help=(
            "直连模式：本机 ds-scheduler-gateway 入口脚本路径"
            "（默认读 DS_GATEWAY_ENTRY，兜底 " + DEFAULT_GATEWAY_ENTRY + "）"
        ),
    )
    parser.add_argument(
        "--ds-token",
        default=None,
        help="巴基斯坦 DS token（默认读 DS_API_TOKEN_PK / PK_DS_TOKEN / DS_TOKEN）",
    )
    parser.add_argument("--bot-id", default=None, help="TV 机器人 ID")
    parser.add_argument(
        "--mentions",
        default=",".join(DEFAULT_MENTIONS),
        help="逗号分隔的提醒邮箱列表",
    )
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--project-code", type=int, default=None)
    parser.add_argument("--workflow-name", default=DEFAULT_WORKFLOW_NAME)
    parser.add_argument("--workflow-code", type=int, default=None)
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    parser.add_argument("--task-code", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    ds_token = (args.ds_token or _env_token()).strip()
    if not ds_token:
        print("❌ 缺少 DS token：请通过 --ds-token 或环境变量 DS_API_TOKEN_PK / PK_DS_TOKEN / DS_TOKEN 提供")
        return 2
    webhook_url = (args.webhook_url or _env_webhook()).strip()
    gateway_entry = (args.gateway_entry or os.environ.get("DS_GATEWAY_ENTRY") or "").strip() or None
    mentions = [item.strip() for item in args.mentions.split(",") if item.strip()]
    try:
        result = run(
            webhook_url=webhook_url,
            ds_token=ds_token,
            dry_run=args.dry_run,
            mentions=mentions,
            bot_id=args.bot_id,
            project_name=args.project_name,
            project_code=args.project_code,
            workflow_name=args.workflow_name,
            workflow_code=args.workflow_code,
            task_name=args.task_name,
            task_code=args.task_code,
            gateway_entry=gateway_entry,
        )
    except Exception as exc:  # noqa: BLE001 - 顶层兜底
        print(f"❌ 告警执行失败: {exc}")
        return 1
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
