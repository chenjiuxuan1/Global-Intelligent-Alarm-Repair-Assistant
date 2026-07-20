#!/usr/bin/env python3
"""
Multi-country DS failed-instance auto retry.

This script is intended to be started by n8n after DolphinScheduler sends a
failure alert. It calls the shared ds-scheduler gateway action retry_instance,
which maps to DolphinScheduler START_FAILURE_TASK_PROCESS.
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
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATEWAY_ENTRY = Path("/root/ds-scheduler-gateway/scripts/ds_scheduler_entry.py")
DEFAULT_TV_URL = "https://tv-service-alert.kuainiu.chat/alert"
DEFAULT_TV_BOT_ID = "fccd2880-baea-42aa-9631-a74ac5d951eb"
DEFAULT_TV_APP_ID = "alert"
DEFAULT_COUNTRY = "ine"
COUNTRY_TV_DEFAULTS = {
    "ph": {
        "url": "https://tv-service-alert.kuainiu.chat/alert",
        "bot_id": "14470d0e-73e2-4411-9306-4cea9a371264",
        "app_id": "",
        "mentions": "simontang@kn.group,jiangchuanchen@kn.group",
    },
}
COUNTRY_NAMES = {
    "cn": "中国",
    "th": "泰国",
    "ine": "印尼",
    "id": "印尼",
    "pk": "巴基斯坦",
    "mx": "墨西哥",
    "ph": "菲律宾",
}

SUCCESS_STATES = {"SUCCESS"}
TERMINAL_FAILURE_STATES = {"FAILURE", "FAILED", "STOP", "KILL", "KILLING"}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _decode_payload(payload_b64: str) -> Any:
    decoded = base64.b64decode(payload_b64).decode("utf-8")
    return json.loads(decoded)


def _walk_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)


def _first_nested(value: Any, aliases: set[str]) -> Any:
    for key, item in _walk_values(value):
        if str(key).lower() in aliases and item not in (None, ""):
            return item
    return None


def _string_blob(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _regex_first(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def normalize_country(country: str) -> str:
    normalized = str(country or DEFAULT_COUNTRY).strip().lower()
    if normalized in {"id", "indonesia"}:
        return "ine"
    return normalized or DEFAULT_COUNTRY


def get_country_tv_config(country: str) -> dict[str, str]:
    normalized = normalize_country(country)
    suffix = normalized.upper()
    defaults = COUNTRY_TV_DEFAULTS.get(normalized, {})
    default_url = defaults["url"] if "url" in defaults else DEFAULT_TV_URL
    default_bot_id = defaults["bot_id"] if "bot_id" in defaults else DEFAULT_TV_BOT_ID
    default_app_id = defaults["app_id"] if "app_id" in defaults else DEFAULT_TV_APP_ID
    default_mentions = defaults["mentions"] if "mentions" in defaults else ""
    return {
        "url": os.getenv(f"DS_FAILED_TV_URL_{suffix}")
        or os.getenv("DS_FAILED_TV_URL")
        or default_url,
        "bot_id": os.getenv(f"DS_FAILED_TV_BOT_ID_{suffix}")
        or os.getenv("DS_FAILED_TV_BOT_ID")
        or default_bot_id,
        "app_id": os.getenv(f"DS_FAILED_TV_APP_ID_{suffix}")
        or os.getenv("DS_FAILED_TV_APP_ID")
        or default_app_id,
        "mentions": os.getenv(f"DS_FAILED_TV_MENTIONS_{suffix}")
        or os.getenv("DS_FAILED_TV_MENTIONS")
        or default_mentions,
    }


def default_state_file(country: str) -> Path:
    return ROOT / "auto_repair_records" / f"{normalize_country(country)}_ds_failed_retry_counts.json"


def normalize_alert_payload(raw: Any, country: str = DEFAULT_COUNTRY) -> dict[str, Any]:
    """Extract the DS fields we need from flexible alert payload shapes."""
    if isinstance(raw, dict) and "body" in raw and isinstance(raw["body"], (dict, str)):
        raw = raw["body"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {"message": raw}

    text = _string_blob(raw)

    def first(*names: str) -> str:
        aliases = {name.lower() for name in names}
        item = _first_nested(raw, aliases)
        return "" if item is None else str(item).strip()

    project_code = first("project_code", "projectCode", "project_code_list")
    instance_id = first(
        "instance_id",
        "process_instance_id",
        "processInstanceId",
        "processInstanceID",
        "process_instance_code",
        "processInstanceCode",
        "workflow_instance_id",
        "workflowInstanceId",
    )
    task_instance_id = first("task_instance_id", "taskInstanceId", "taskInstanceID")

    if not project_code:
        project_code = _regex_first(
            text,
            [
                r"project[_\s-]*code[\"'\s:=：]+(\d+)",
                r"项目编码[\"'\s:=：]+(\d+)",
                r"projectCode[\"'\s:=：]+(\d+)",
            ],
        )
    if not instance_id:
        instance_id = _regex_first(
            text,
            [
                r"process[_\s-]*instance[_\s-]*(?:id|code)[\"'\s:=：]+(\d+)",
                r"processInstance(?:Id|Code)[\"'\s:=：]+(\d+)",
                r"workflowInstanceId[\"'\s:=：]+(\d+)",
                r"workflow[_\s-]*instance[_\s-]*id[\"'\s:=：]+(\d+)",
                r"instance[_\s-]*id[\"'\s:=：]+(\d+)",
                r"实例(?:ID|编码)?[\"'\s:=：]+(\d+)",
            ],
        )

    ds_token = first("ds_token", "dsToken", "token", "dolphinscheduler_token")
    workflow_name = first(
        "workflow_name",
        "workflow_instance_name",
        "workflowInstanceName",
        "process_definition_name",
        "processDefinitionName",
        "processName",
    )
    task_name = first("task_name", "taskName", "failed_task_name", "failedTaskName")
    project_name = first("project_name", "projectName")
    workflow_definition_code = first(
        "workflow_definition_code",
        "workflowDefinitionCode",
        "process_definition_code",
        "processDefinitionCode",
    )
    workflow_execution_status = first(
        "workflow_execution_status",
        "workflowExecutionStatus",
        "execution_status",
        "executionStatus",
    )
    workflow_start_time = first("workflow_start_time", "workflowStartTime", "start_time", "startTime")
    workflow_end_time = first("workflow_end_time", "workflowEndTime", "end_time", "endTime")
    workflow_host = first("workflow_host", "workflowHost", "host")
    run_times = first("run_times", "runTimes")

    country = normalize_country(country or first("country", "country_code", "countryCode") or DEFAULT_COUNTRY)
    retry_key = f"{country}:{project_code}:{instance_id}"
    return {
        "country": country,
        "project_code": project_code,
        "project_name": project_name,
        "instance_id": instance_id,
        "process_instance_id": instance_id,
        "task_instance_id": task_instance_id,
        "workflow_definition_code": workflow_definition_code,
        "workflow_name": workflow_name,
        "workflow_execution_status": workflow_execution_status,
        "workflow_start_time": workflow_start_time,
        "workflow_end_time": workflow_end_time,
        "workflow_host": workflow_host,
        "run_times": run_times,
        "task_name": task_name,
        "ds_token": ds_token,
        "retry_key": retry_key,
        "raw": raw,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def record_attempt(state_file: Path, retry_key: str) -> int:
    state = _read_json(state_file)
    item = state.get(retry_key) or {"attempts": 0}
    attempts = int(item.get("attempts") or 0) + 1
    state[retry_key] = {
        **item,
        "attempts": attempts,
        "last_attempt_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json(state_file, state)
    return attempts


def clear_attempts(state_file: Path, retry_key: str) -> None:
    state = _read_json(state_file)
    if retry_key in state:
        del state[retry_key]
        _write_json(state_file, state)


def current_attempts(state_file: Path, retry_key: str) -> int:
    state = _read_json(state_file)
    return int((state.get(retry_key) or {}).get("attempts") or 0)


def _payload_b64(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def run_gateway_action(
    action: str,
    ds_token: str,
    payload: dict[str, Any],
    request_id: str,
    country: str = DEFAULT_COUNTRY,
    gateway_entry: Path = DEFAULT_GATEWAY_ENTRY,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(gateway_entry),
        "--country",
        normalize_country(country),
        "--action",
        action,
        "--ds-token",
        ds_token,
        "--request-id",
        request_id,
        "--payload-b64",
        _payload_b64(payload),
    ]
    completed = subprocess.run(cmd, text=True, capture_output=True, timeout=120, check=False)
    stdout = completed.stdout.strip()
    try:
        parsed = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        parsed = {"raw_stdout": stdout}
    return {
        "ok": completed.returncode == 0 and bool(parsed.get("success", True)),
        "returncode": completed.returncode,
        "stdout": parsed,
        "stderr": completed.stderr.strip(),
    }


def extract_instance_state(response: dict[str, Any]) -> str:
    data = response.get("stdout", response)
    candidates: list[Any] = [data]
    if isinstance(data, dict):
        candidates.extend([data.get("data"), data.get("result")])
        nested = data.get("data")
        if isinstance(nested, dict):
            candidates.extend([nested.get("data"), nested.get("processInstance")])

    for candidate in candidates:
        if isinstance(candidate, dict):
            for key in ("state", "stateType", "status", "executionStatus"):
                value = candidate.get(key)
                if value not in (None, ""):
                    return str(value).strip().upper()
    return "UNKNOWN"


def extract_failure_reason(response: dict[str, Any]) -> str:
    data = response.get("stdout", response)
    reason_keys = {
        "failurereason",
        "failure_reason",
        "reason",
        "errormessage",
        "error_message",
        "message",
        "msg",
        "log",
    }
    for key, item in _walk_values(data):
        if str(key).lower() not in reason_keys or item in (None, ""):
            continue
        text = str(item).strip()
        if text and text.lower() not in {"success", "ok", "none", "null"}:
            return text[:1000]
    stderr = str(response.get("stderr") or "").strip()
    if stderr:
        return stderr[:1000]
    return "未从 DS 实例详情中解析到明确失败原因，请查看 DS 实例日志"


def send_tv_alert(message: str, url: str, bot_id: str, app_id: str = "") -> dict[str, Any]:
    payload = {
        "botId": bot_id,
        "message": message,
    }
    if app_id:
        payload["appId"] = app_id
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return {
                "success": 200 <= response.status < 300,
                "status_code": response.status,
                "response": response.read().decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {"success": False, "status_code": exc.code, "response": body}
    except Exception as exc:
        return {"success": False, "status_code": None, "response": str(exc)}


def _alert_payload_text(alert: dict[str, Any], unwrap_single: bool = True) -> str:
    raw = alert.get("raw")
    if unwrap_single and isinstance(raw, list) and len(raw) == 1:
        raw = raw[0]
    if raw in (None, ""):
        raw = {
            "projectCode": alert.get("project_code") or "",
            "projectName": alert.get("project_name") or "",
            "workflowInstanceId": alert.get("instance_id") or "",
            "workflowDefinitionCode": alert.get("workflow_definition_code") or "",
            "workflowInstanceName": alert.get("workflow_name") or "",
            "workflowExecutionStatus": alert.get("workflow_execution_status") or "",
            "runTimes": alert.get("run_times") or "",
            "workflowStartTime": alert.get("workflow_start_time") or "",
            "workflowEndTime": alert.get("workflow_end_time") or "",
            "workflowHost": alert.get("workflow_host") or "",
        }
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


def _mentions_text(mentions: str) -> str:
    return " ".join(f"@{item.strip().lstrip('@')}" for item in str(mentions or "").split(",") if item.strip())


def build_retry_progress_message(alert: dict[str, Any], attempts: int, reason: str) -> str:
    return "\n".join(
        [
            _alert_payload_text(alert, unwrap_single=False),
            f"定时任务执行失败，失败原因：{reason or '未从 DS 实例详情中解析到明确失败原因，请查看 DS 实例日志'}",
            f"目前自动失败重试中，执行次数：{attempts}",
        ]
    )


def build_failure_message(
    alert: dict[str, Any],
    attempts: int,
    state: str,
    last_result: dict[str, Any],
    mentions: str = "",
) -> str:
    reason = extract_failure_reason(last_result)
    tail = f"目前自动失败重试中，执行次数：{attempts}，当前重试次数已达上限，需要负责人查看处理"
    mention_text = _mentions_text(mentions)
    if mention_text:
        tail = f"{tail}{mention_text}"
    return "\n".join(
        [
            _alert_payload_text(alert),
            f"定时任务执行失败，失败原因：{reason}",
            tail,
        ]
    )


def build_failure_debug_message(alert: dict[str, Any], attempts: int, state: str, last_result: dict[str, Any]) -> str:
    country = normalize_country(alert.get("country") or DEFAULT_COUNTRY)
    country_name = COUNTRY_NAMES.get(country, country)
    lines = [
        f"{country_name} DolphinScheduler 失败任务自动重跑未恢复",
        f"重跑次数: {attempts}",
        f"最终状态: {state}",
        f"项目编码: {alert.get('project_code') or '-'}",
        f"实例ID: {alert.get('instance_id') or '-'}",
    ]
    if alert.get("project_name"):
        lines.append(f"项目名称: {alert['project_name']}")
    if alert.get("workflow_definition_code"):
        lines.append(f"工作流定义编码: {alert['workflow_definition_code']}")
    if alert.get("workflow_name"):
        lines.append(f"工作流: {alert['workflow_name']}")
    if alert.get("task_name"):
        lines.append(f"失败任务: {alert['task_name']}")
    if alert.get("workflow_start_time"):
        lines.append(f"开始时间: {alert['workflow_start_time']}")
    if alert.get("workflow_end_time"):
        lines.append(f"结束时间: {alert['workflow_end_time']}")
    if alert.get("workflow_host"):
        lines.append(f"执行机器: {alert['workflow_host']}")
    if alert.get("run_times"):
        lines.append(f"DS运行次数: {alert['run_times']}")
    stderr = str(last_result.get("stderr") or "").strip()
    if stderr:
        lines.append(f"网关错误: {stderr[:500]}")
    return "\n".join(lines)


def auto_retry(
    alert: dict[str, Any],
    ds_token: str,
    max_attempts: int,
    retry_delay_seconds: int,
    state_file: Path,
    sleep: Callable[[int], None] = time.sleep,
    gateway_runner: Callable[[str, str, dict[str, Any], str], dict[str, Any]] | None = None,
    tv_sender: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gateway_runner = gateway_runner or (
        lambda action, token, payload, request_id: run_gateway_action(
            action,
            token,
            payload,
            request_id,
            country=alert.get("country") or DEFAULT_COUNTRY,
        )
    )
    if tv_sender is None:
        tv_config = get_country_tv_config(alert.get("country") or DEFAULT_COUNTRY)
        tv_sender = lambda message: send_tv_alert(
            message,
            tv_config["url"],
            tv_config["bot_id"],
            tv_config["app_id"],
        )

    errors = []
    if not alert.get("project_code"):
        errors.append("project_code is required")
    if not alert.get("instance_id"):
        errors.append("instance_id is required")
    if not ds_token:
        errors.append("ds_token is required")
    if errors:
        return {"success": False, "error": "; ".join(errors), "alert": alert}

    retry_key = alert["retry_key"]
    initial_attempts = current_attempts(state_file, retry_key)
    if initial_attempts >= max_attempts:
        tv_config = get_country_tv_config(alert.get("country") or DEFAULT_COUNTRY)
        message = build_failure_message(alert, initial_attempts, "MAX_ATTEMPTS_REACHED", {}, tv_config["mentions"])
        tv_result = tv_sender(message)
        return {
            "success": False,
            "status": "max_attempts_reached",
            "attempts": initial_attempts,
            "tv_result": tv_result,
        }

    last_result: dict[str, Any] = {}
    progress_tv_result: dict[str, Any] = {}
    state = "UNKNOWN"
    attempts = initial_attempts

    while attempts < max_attempts:
        attempts = record_attempt(state_file, retry_key)
        country = normalize_country(alert.get("country") or DEFAULT_COUNTRY)
        request_id = f"{country}-ds-auto-retry-{alert['instance_id']}-{attempts}"
        payload = {
            "project_code": alert["project_code"],
            "instance_id": alert["instance_id"],
            "process_instance_id": alert["instance_id"],
        }
        pre_check_result = gateway_runner("get_instance", ds_token, payload, f"{request_id}-before")
        progress_reason = extract_failure_reason(pre_check_result)
        progress_tv_result = tv_sender(build_retry_progress_message(alert, attempts, progress_reason))
        last_result = gateway_runner("retry_instance", ds_token, payload, request_id)
        if not last_result.get("ok"):
            state = "RETRY_ACTION_FAILED"
        else:
            sleep(retry_delay_seconds)
            check_result = gateway_runner("get_instance", ds_token, payload, f"{request_id}-check")
            last_result = check_result
            state = extract_instance_state(check_result)

        if state in SUCCESS_STATES:
            clear_attempts(state_file, retry_key)
            return {"success": True, "status": "recovered", "attempts": attempts, "state": state}

        if state not in TERMINAL_FAILURE_STATES and state not in {"UNKNOWN", "RETRY_ACTION_FAILED"}:
            return {"success": True, "status": "still_running", "attempts": attempts, "state": state}

    tv_config = get_country_tv_config(alert.get("country") or DEFAULT_COUNTRY)
    message = build_failure_message(alert, attempts, state, last_result, tv_config["mentions"])
    tv_result = tv_sender(message)
    return {
        "success": False,
        "status": "failed_after_max_attempts",
        "attempts": attempts,
        "state": state,
        "progress_tv_result": progress_tv_result,
        "tv_result": tv_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", default=os.getenv("APP_COUNTRY", DEFAULT_COUNTRY))
    parser.add_argument("--payload-b64", required=True)
    parser.add_argument("--ds-token", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("DS_FAILED_MAX_RETRIES", "3")))
    parser.add_argument("--retry-delay-seconds", type=int, default=int(os.getenv("DS_FAILED_RETRY_DELAY_SECONDS", "180")))
    parser.add_argument("--state-file", default="")
    args = parser.parse_args(argv)

    _load_dotenv(ROOT / ".env.local")
    raw = _decode_payload(args.payload_b64)
    country = normalize_country(args.country)
    alert = normalize_alert_payload(raw, country=country)
    ds_token = args.ds_token.strip() or alert.get("ds_token") or os.getenv("DS_TOKEN", "")
    state_file = Path(args.state_file) if args.state_file else default_state_file(country)

    result = auto_retry(
        alert=alert,
        ds_token=ds_token,
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
        state_file=state_file,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
