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
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    from tools.ds_retry_monitor_registry import CountryMonitorRegistry
except ModuleNotFoundError:  # Direct execution adds tools/, not the repository root, to sys.path.
    from ds_retry_monitor_registry import CountryMonitorRegistry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATEWAY_ENTRY = Path("/root/ds-scheduler-gateway/scripts/ds_scheduler_entry.py")
DEFAULT_TV_URL = "https://tv-service-alert.kuainiu.chat/alert"
DEFAULT_TV_BOT_ID = "fccd2880-baea-42aa-9631-a74ac5d951eb"
DEFAULT_TV_APP_ID = "alert"
DEFAULT_COUNTRY = "ine"
DEFAULT_TASK_LOG_LIMIT = 100_000
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
TERMINAL_FAILURE_STATES = {"FAILURE", "FAILED", "STOP", "KILL", "KILLING", "6"}
GENERIC_FAILURE_REASON = "未从 DS 实例详情中解析到明确失败原因，请查看 DS 实例日志"
FAILED_TASK_STATES = {"FAILURE", "FAILED", "STOP", "KILL", "KILLING", "ERROR", "6"}
COUNTRY_FALLBACK_MENTIONS = {
    "cn": "gretchenhe@kn.group",
    "ine": "gretchenhe@kn.group",
    "mx": "kuiwu@kn.group",
    "ph": "simontang@kn.group",
    "pk": "adamyu@kn.group",
    "th": "qilonghuang@kn.group",
}


def _is_failure_wrapper_reason(reason: str) -> bool:
    """Return whether DS returned the ETL launcher's generic final line.

    Matches the full DS log form (``console - ERROR - run etl fail``) as well as
    the bare form (``run etl fail``) that remains after prefix stripping.
    """
    normalized = re.sub(r"\s+", " ", str(reason or "")).strip().lower()
    return bool(
        re.search(r"\b(?:console\s*-\s*)?(?:error\s*-\s*)?run etl fail\b", normalized)
    )


# DolphinScheduler worker logs wrap every task-output line with a prefix like
# ``2026-08-03 18:25:27.026 INFO  -  -> ``.  The ETL launcher itself adds a
# second prefix (``2026-08-03 18:25:27,026 - console - ERROR - ``).  Strip both
# so the failure reason surfaced in TV alerts is the actual task message.
_DS_LOG_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d{3}\s+\w+\s+-\s+->\s*"
)
_TASK_LOG_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d{3}\s+-\s+\S+\s+-\s+\w+\s+-\s*"
)


def _strip_ds_log_prefix(line: str) -> str:
    """Remove DolphinScheduler and task-internal log prefixes from a single line."""
    line = _DS_LOG_PREFIX_RE.sub("", line, count=1)
    line = _TASK_LOG_PREFIX_RE.sub("", line, count=1)
    return line.strip()


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


def default_monitor_registry_file(country: str) -> Path:
    return ROOT / "auto_repair_records" / f"{normalize_country(country)}_ds_active_retry_monitors.json"


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


def failure_context(state_file: Path, retry_key: str) -> dict[str, str]:
    item = _read_json(state_file).get(retry_key) or {}
    return {
        "reason": str(item.get("last_failure_reason") or "").strip(),
        "mentions": str(item.get("mentions") or "").strip(),
        "task_name": str(item.get("failed_task_name") or "").strip(),
    }


def record_failure_context(
    state_file: Path,
    retry_key: str,
    reason: str,
    mentions: str,
    task_name: str = "",
) -> None:
    state = _read_json(state_file)
    item = state.get(retry_key) or {"attempts": 0}
    state[retry_key] = {
        **item,
        "last_failure_reason": str(reason or "").strip(),
        "mentions": str(mentions or "").strip(),
        "failed_task_name": str(task_name or item.get("failed_task_name") or "").strip(),
    }
    _write_json(state_file, state)


def max_attempts_notified(state_file: Path, retry_key: str) -> bool:
    return bool((_read_json(state_file).get(retry_key) or {}).get("max_attempts_notified"))


def mark_max_attempts_notified(state_file: Path, retry_key: str) -> None:
    state = _read_json(state_file)
    item = state.get(retry_key) or {"attempts": 0}
    state[retry_key] = {
        **item,
        "max_attempts_notified": True,
        "max_attempts_notified_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json(state_file, state)


def _lock_path(state_file: Path, retry_key: str) -> Path:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", retry_key)
    return state_file.parent / f".{safe_key}.lock"


@contextmanager
def retry_lock(state_file: Path, retry_key: str) -> Iterator[bool]:
    """Acquire a non-blocking per-instance lock; duplicate alerts simply exit."""
    lock_path = _lock_path(state_file, retry_key)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


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
            # DS may put the complete worker log into errorMessage. Apply the
            # same root-cause extraction used for get_task_log so a progress
            # alert never expands into Java stack frames and duplicate lines.
            summary = _summarize_task_log(text) or text[:1000]
            if not _is_failure_wrapper_reason(summary):
                return summary
    stderr = str(response.get("stderr") or "").strip()
    if stderr:
        summary = _summarize_task_log(stderr) or stderr[:1000]
        if not _is_failure_wrapper_reason(summary):
            return summary
    return GENERIC_FAILURE_REASON


def _task_instances_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract task instances from the gateway's list_task_instances response."""
    data = response.get("stdout", response)
    candidates: list[Any] = [data]
    # The local gateway wraps the original DS response once, and DS itself
    # commonly wraps list rows in another `data` object.
    for _ in range(3):
        current = candidates[-1]
        if not isinstance(current, dict) or "data" not in current:
            break
        candidates.append(current["data"])

    for payload in candidates:
        if isinstance(payload, dict):
            for key in ("totalList", "records", "list"):
                items = payload.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    return []


def _is_failed_task(task: dict[str, Any]) -> bool:
    state = str(
        task.get("stateDesc")
        or task.get("state")
        or task.get("executionStatus")
        or task.get("status")
        or ""
    ).strip().upper()
    return state in FAILED_TASK_STATES


def _summarize_task_log(value: Any) -> str:
    """Return a compact, useful tail from a DS task log.

    The ETL launcher always emits a generic ``ERROR - run etl fail`` as its final
    line.  That line is *not* the root cause, so skip it (and any other wrapper
    variant) when scanning backwards for the real error.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    # Some gateway/JSON wrappers return escaped newlines as literal ``\\n``.
    if "\n" not in text and "\\n" in text:
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    raw_lines = [line for line in text.splitlines() if line.strip()]
    lines = [_strip_ds_log_prefix(line) for line in raw_lines]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    # A Java `Caused by` line is usually the root cause. Prefer it to executor
    # messages and stack frames so TV notifications remain actionable.
    for line in reversed(lines):
        match = re.search(r"caused by:\s*(.+)", line, flags=re.IGNORECASE)
        if match:
            caused = match.group(1).strip()[:1000]
            if caused and not _is_failure_wrapper_reason(caused):
                return caused

    # Prefer text emitted at an explicit ERROR/FATAL log level.  Inspect the
    # raw line because prefix stripping deliberately removes that level from
    # task-internal log lines such as ``console - ERROR - Connection refused``.
    for raw_line in reversed(raw_lines):
        match = re.search(
            r"(?:^|\s+-\s+|\[)(?:error|fatal)\]?\s*(?:[-:]\s*)?(.*)$",
            raw_line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        cleaned = _strip_ds_log_prefix(raw_line)
        explicit = match.group(1).strip()
        candidate = cleaned if re.match(r"^(?:error|fatal)\b", cleaned, flags=re.IGNORECASE) else explicit
        if candidate and not _is_failure_wrapper_reason(candidate):
            return candidate[:1000]

    for line in reversed(lines):
        if re.search(r"\bexception\b|\bfailed\b|\berror\s*:|失败", line, flags=re.IGNORECASE):
            if _is_failure_wrapper_reason(line):
                continue
            return line[:1000]

    # No explicit error evidence means this may be a truncated SQL/script page.
    # Returning its last line creates false reasons such as ``MAX(IF(...))``.
    return ""


def extract_task_log_failure_reason(response: dict[str, Any]) -> str:
    """Read the actual log text returned by get_task_log, not API wrapper messages."""
    data = response.get("stdout", response)
    for key, value in _walk_values(data):
        if str(key).lower() in {"log", "logcontent", "log_content", "content"}:
            summary = _summarize_task_log(value)
            if summary and not _is_failure_wrapper_reason(summary):
                return summary
    return ""


def git_task_owner(country: str, task_name: str) -> str:
    """Return the e-mail from the latest Git commit touching code named by a DS task."""
    task_name = str(task_name or "").strip()
    root = Path(os.getenv("WORKFLOW_CODE_ROOT", "/data/git/starrocks/workflow"))
    if not task_name:
        return ""
    # Keep this aligned with the workflow-code directory configured for the
    # repair service; APP_COUNTRY is only a sensible fallback.
    scope = os.getenv("WORKFLOW_CODE_COUNTRY", normalize_country(country)).strip() or normalize_country(country)
    country_root = root / scope
    if (country_root / ".git").exists():
        repo_root = country_root
        pathspec: list[str] = []
    elif (root / ".git").exists() and country_root.is_dir():
        repo_root = root
        pathspec = [scope]
    else:
        return ""
    try:
        grep_cmd = ["git", "-C", str(repo_root), "grep", "-l", "-F", "--", task_name]
        if pathspec:
            grep_cmd.extend(["--", *pathspec])
        matched = subprocess.run(
            grep_cmd,
            text=True, capture_output=True, timeout=10, check=False,
        )
        paths = [line.strip() for line in matched.stdout.splitlines() if line.strip()]
        if not paths:
            return ""
        author = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%ae", "--", paths[0]],
            text=True, capture_output=True, timeout=10, check=False,
        ).stdout.strip()
        return author if "@" in author else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def resolve_mentions(country: str, task_name: str, configured_mentions: str = "") -> str:
    return git_task_owner(country, task_name) or COUNTRY_FALLBACK_MENTIONS.get(
        normalize_country(country), configured_mentions,
    )


def fetch_failure_info_from_task_log(
    alert: dict[str, Any],
    ds_token: str,
    request_id: str,
    gateway_runner: Callable[[str, str, dict[str, Any], str], dict[str, Any]],
    lookup_attempts: int = 1,
    lookup_delay_seconds: int = 0,
    sleep: Callable[[int], None] = time.sleep,
) -> tuple[str, str]:
    """Find failed task instances and return the first available failed-task log tail.

    DS emits a process failure alert before its task-instance list and worker log
    are occasionally visible. Retry this read-only lookup briefly in that case.
    """
    payload = {
        "project_code": alert["project_code"],
        "instance_id": alert["instance_id"],
        "process_instance_id": alert["instance_id"],
        "page_size": 100,
    }
    task_log_limit = max(
        2001,
        int(os.getenv("DS_FAILED_TASK_LOG_LIMIT", str(DEFAULT_TASK_LOG_LIMIT))),
    )
    lookup_attempts = max(1, int(lookup_attempts))
    for lookup_index in range(lookup_attempts):
        task_list_response = gateway_runner(
            "list_task_instances", ds_token, payload, f"{request_id}-tasks-{lookup_index + 1}"
        )
        failed_tasks = [task for task in _task_instances_from_response(task_list_response) if _is_failed_task(task)]
        for task in failed_tasks:
            task_instance_id = task.get("id") or task.get("taskInstanceId")
            if not task_instance_id:
                continue
            log_response = gateway_runner(
                "get_task_log",
                ds_token,
                {
                    **payload,
                    "task_instance_id": task_instance_id,
                    "task_name": task.get("name") or task.get("taskName") or "",
                    "task_code": task.get("taskCode") or "",
                    "limit": task_log_limit,
                },
                f"{request_id}-task-{task_instance_id}-log-{lookup_index + 1}",
            )
            reason = extract_task_log_failure_reason(log_response)
            if reason:
                return reason, str(task.get("name") or task.get("taskName") or "").strip()
        if lookup_index + 1 < lookup_attempts and lookup_delay_seconds > 0:
            sleep(lookup_delay_seconds)
    return "", ""


def fetch_failure_reason_from_task_log(*args: Any, **kwargs: Any) -> str:
    return fetch_failure_info_from_task_log(*args, **kwargs)[0]


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


def build_retry_progress_message(
    alert: dict[str, Any],
    attempts: int,
    reason: str,
    mentions: str = "",
    task_name: str = "",
) -> str:
    failed_task = str(task_name or alert.get("task_name") or "").strip()
    return "\n".join(
        [
            _alert_payload_text(alert, unwrap_single=False),
            *([f"失败任务：{failed_task}"] if failed_task else []),
            f"定时任务执行失败，失败原因：{reason or '未从 DS 实例详情中解析到明确失败原因，请查看 DS 实例日志'}",
            f"目前自动失败重试中，执行次数：{attempts}{_mentions_text(mentions)}",
        ]
    )


def build_failure_message(
    alert: dict[str, Any],
    attempts: int,
    state: str,
    last_result: dict[str, Any],
    mentions: str = "",
    failure_reason: str = "",
    task_name: str = "",
) -> str:
    reason = failure_reason or extract_failure_reason(last_result)
    failed_task = str(task_name or alert.get("task_name") or "").strip()
    tail = f"目前自动失败重试中，执行次数：{attempts}，当前重试次数已达上限，需要负责人查看处理"
    mention_text = _mentions_text(mentions)
    if mention_text:
        tail = f"{tail}{mention_text}"
    return "\n".join(
        [
            _alert_payload_text(alert),
            *([f"失败任务：{failed_task}"] if failed_task else []),
            f"定时任务执行失败，失败原因：{reason}",
            tail,
        ]
    )


def build_recovered_message(
    alert: dict[str, Any],
    attempts: int,
    reason: str,
    mentions: str = "",
    task_name: str = "",
) -> str:
    failed_task = str(task_name or alert.get("task_name") or "").strip()
    tail = f"自动重跑已恢复成功，重跑次数：{attempts}"
    mention_text = _mentions_text(mentions)
    if mention_text:
        tail = f"{tail}{mention_text}"
    return "\n".join(
        [
            _alert_payload_text(alert),
            *([f"原失败任务：{failed_task}"] if failed_task else []),
            f"定时任务原失败原因：{reason or GENERIC_FAILURE_REASON}",
            tail,
        ]
    )


def build_still_running_message(
    alert: dict[str, Any],
    attempts: int,
    reason: str,
    mentions: str = "",
    task_name: str = "",
) -> str:
    failed_task = str(task_name or alert.get("task_name") or "").strip()
    tail = f"自动重跑后任务仍在运行中，重跑次数：{attempts}"
    mention_text = _mentions_text(mentions)
    if mention_text:
        tail = f"{tail}{mention_text}"
    return "\n".join(
        [
            _alert_payload_text(alert),
            *([f"原失败任务：{failed_task}"] if failed_task else []),
            f"定时任务原失败原因：{reason or GENERIC_FAILURE_REASON}",
            tail,
        ]
    )


def build_country_unhealthy_message(
    country: str,
    active_count: int,
    circuit_open_until: float,
    mentions: str = "",
) -> str:
    normalized = normalize_country(country)
    country_name = COUNTRY_NAMES.get(normalized, normalized)
    open_until = datetime.fromtimestamp(circuit_open_until).strftime("%Y-%m-%d %H:%M:%S")
    tail = (
        f"当前同时处于自动重跑/监控中的失败工作流实例数已达到 {active_count}，"
        "已停止该国家全部自动重跑和监控。DolphinScheduler 当前状态不太健康，"
        f"需要负责人查看；熔断保持 30 分钟，本次最早解除时间：{open_until}"
    )
    mention_text = _mentions_text(mentions)
    if mention_text:
        tail = f"{tail}{mention_text}"
    return f"{country_name} {tail}"


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
    monitor_guard: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tv_config = get_country_tv_config(alert.get("country") or DEFAULT_COUNTRY)
    reason_lookup_attempts = max(1, int(os.getenv("DS_FAILED_REASON_LOOKUP_ATTEMPTS", "3")))
    reason_lookup_delay_seconds = max(0, int(os.getenv("DS_FAILED_REASON_LOOKUP_DELAY_SECONDS", "5")))
    monitor_interval_seconds = max(0, int(os.getenv("DS_FAILED_MONITOR_INTERVAL_SECONDS", "60")))
    monitor_timeout_seconds = max(1, int(os.getenv("DS_FAILED_MONITOR_TIMEOUT_SECONDS", "86400")))
    monitor_max_checks = max(
        1,
        monitor_timeout_seconds // max(monitor_interval_seconds, 1),
    )
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
        if max_attempts_notified(state_file, retry_key):
            return {
                "success": True,
                "status": "max_attempts_already_notified",
                "attempts": initial_attempts,
            }
        cached_context = failure_context(state_file, retry_key)
        max_attempt_reason, task_name = fetch_failure_info_from_task_log(
            alert,
            ds_token,
            f"{normalize_country(alert.get('country') or DEFAULT_COUNTRY)}-ds-auto-retry-{alert['instance_id']}-{initial_attempts}",
            gateway_runner,
            lookup_attempts=reason_lookup_attempts,
            lookup_delay_seconds=reason_lookup_delay_seconds,
            sleep=sleep,
        )
        reason = max_attempt_reason or cached_context["reason"] or GENERIC_FAILURE_REASON
        task_name = task_name or cached_context["task_name"] or alert.get("task_name") or ""
        mentions = cached_context["mentions"] or resolve_mentions(
            alert.get("country") or DEFAULT_COUNTRY,
            task_name or alert.get("task_name") or "",
            tv_config["mentions"],
        )
        if reason != GENERIC_FAILURE_REASON:
            record_failure_context(state_file, retry_key, reason, mentions, task_name)
        message = build_failure_message(
            alert,
            initial_attempts,
            "MAX_ATTEMPTS_REACHED",
            {},
            mentions,
            failure_reason=reason,
            task_name=task_name,
        )
        tv_result = tv_sender(message)
        mark_max_attempts_notified(state_file, retry_key)
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
        if monitor_guard is not None:
            monitor_decision = monitor_guard()
            if monitor_decision.get("circuit_open"):
                return {
                    "success": True,
                    "status": "country_circuit_open",
                    "attempts": attempts,
                    "active_count": monitor_decision.get("active_count", 0),
                }
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
        task_name = alert.get("task_name") or ""
        if extract_instance_state(pre_check_result) in TERMINAL_FAILURE_STATES:
            fetched_reason, fetched_task_name = fetch_failure_info_from_task_log(
                alert,
                ds_token,
                request_id,
                gateway_runner,
                lookup_attempts=reason_lookup_attempts,
                lookup_delay_seconds=reason_lookup_delay_seconds,
                sleep=sleep,
            )
            # Task-instance logs are authoritative. Process-instance
            # errorMessage is only a fallback because it can be a wrapper or a
            # downstream exception with no failed-node identity.
            progress_reason = fetched_reason or progress_reason
            task_name = fetched_task_name or task_name
        cached_context = failure_context(state_file, retry_key)
        mentions = cached_context["mentions"] or resolve_mentions(
            country, task_name, tv_config["mentions"]
        )
        if progress_reason != GENERIC_FAILURE_REASON:
            record_failure_context(state_file, retry_key, progress_reason, mentions, task_name)
        else:
            progress_reason = cached_context["reason"] or progress_reason
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
            recovered_reason = progress_reason if progress_reason != GENERIC_FAILURE_REASON else cached_context["reason"]
            recovered_message = build_recovered_message(
                alert, attempts, recovered_reason, mentions, task_name=task_name
            )
            recovered_tv_result = tv_sender(recovered_message)
            return {"success": True, "status": "recovered", "attempts": attempts, "state": state, "tv_result": recovered_tv_result}

        if state not in TERMINAL_FAILURE_STATES and state not in {"UNKNOWN", "RETRY_ACTION_FAILED"}:
            running_reason = progress_reason if progress_reason != GENERIC_FAILURE_REASON else cached_context["reason"]
            running_message = build_still_running_message(
                alert, attempts, running_reason, mentions, task_name=task_name
            )
            progress_tv_result = tv_sender(running_message)

            # The retry action is asynchronous. Keep this background process
            # alive after the first RUNNING state so a later SUCCESS can still
            # be reported instead of silently ending after the progress alert.
            monitor_checks = 0
            while monitor_checks < monitor_max_checks:
                sleep(monitor_interval_seconds)
                if monitor_guard is not None:
                    monitor_decision = monitor_guard()
                    if monitor_decision.get("circuit_open"):
                        return {
                            "success": True,
                            "status": "country_circuit_open",
                            "attempts": attempts,
                            "state": state,
                            "active_count": monitor_decision.get("active_count", 0),
                        }
                monitor_checks += 1
                check_result = gateway_runner(
                    "get_instance",
                    ds_token,
                    payload,
                    f"{request_id}-monitor-{monitor_checks}",
                )
                last_result = check_result
                state = extract_instance_state(check_result)

                if state in SUCCESS_STATES:
                    clear_attempts(state_file, retry_key)
                    recovered_message = build_recovered_message(
                        alert,
                        attempts,
                        running_reason,
                        mentions,
                        task_name=task_name,
                    )
                    recovered_tv_result = tv_sender(recovered_message)
                    return {
                        "success": True,
                        "status": "recovered",
                        "attempts": attempts,
                        "state": state,
                        "progress_tv_result": progress_tv_result,
                        "tv_result": recovered_tv_result,
                    }

                # A transient UNKNOWN is a read failure, not evidence that the
                # running retry ended. Keep monitoring to avoid launching a
                # duplicate retry against the same process instance.
                if state in TERMINAL_FAILURE_STATES:
                    break
            else:
                return {
                    "success": True,
                    "status": "still_running",
                    "attempts": attempts,
                    "state": state,
                    "monitor_checks": monitor_checks,
                    "tv_result": progress_tv_result,
                }

    final_reason = extract_failure_reason(last_result)
    task_name = alert.get("task_name") or ""
    fetched_reason = ""
    if state in TERMINAL_FAILURE_STATES:
        fetched_reason, fetched_task_name = fetch_failure_info_from_task_log(
            alert,
            ds_token,
            f"{normalize_country(alert.get('country') or DEFAULT_COUNTRY)}-ds-auto-retry-{alert['instance_id']}-{attempts}",
            gateway_runner,
            lookup_attempts=reason_lookup_attempts,
            lookup_delay_seconds=reason_lookup_delay_seconds,
            sleep=sleep,
        )
        final_reason = fetched_reason or final_reason
        task_name = fetched_task_name or task_name
    cached_context = failure_context(state_file, retry_key)
    final_reason = fetched_reason or cached_context["reason"] or final_reason
    task_name = task_name or cached_context["task_name"]
    mentions = cached_context["mentions"] or resolve_mentions(
        alert.get("country") or DEFAULT_COUNTRY, task_name, tv_config["mentions"]
    )
    if final_reason != GENERIC_FAILURE_REASON:
        record_failure_context(state_file, retry_key, final_reason, mentions, task_name)
    message = build_failure_message(
        alert,
        attempts,
        state,
        last_result,
        mentions,
        failure_reason=final_reason,
        task_name=task_name,
    )
    tv_result = tv_sender(message)
    mark_max_attempts_notified(state_file, retry_key)
    return {
        "success": False,
        "status": "failed_after_max_attempts",
        "attempts": attempts,
        "state": state,
        "progress_tv_result": progress_tv_result,
        "tv_result": tv_result,
    }


def run_registered_auto_retry(
    *,
    alert: dict[str, Any],
    ds_token: str,
    max_attempts: int,
    retry_delay_seconds: int,
    state_file: Path,
    request_id: str = "",
    registry: CountryMonitorRegistry | None = None,
    pid: int | None = None,
    tv_sender: Callable[[str], dict[str, Any]] | None = None,
    auto_retry_runner: Callable[..., dict[str, Any]] = auto_retry,
) -> dict[str, Any]:
    country = normalize_country(alert.get("country") or DEFAULT_COUNTRY)
    tv_config = get_country_tv_config(country)
    if tv_sender is None:
        tv_sender = lambda message: send_tv_alert(
            message,
            tv_config["url"],
            tv_config["bot_id"],
            tv_config["app_id"],
        )
    registry = registry or CountryMonitorRegistry(
        default_monitor_registry_file(country),
        active_limit=int(os.getenv("DS_FAILED_COUNTRY_ACTIVE_LIMIT", "10")),
        circuit_seconds=int(os.getenv("DS_FAILED_COUNTRY_CIRCUIT_SECONDS", "1800")),
        stale_seconds=int(os.getenv("DS_FAILED_MONITOR_STALE_SECONDS", "300")),
    )
    monitor_pid = int(pid if pid is not None else os.getpid())
    retry_key = alert["retry_key"]
    decision = registry.register(
        retry_key,
        pid=monitor_pid,
        request_id=request_id,
        instance_id=str(alert.get("instance_id") or ""),
    )
    if decision.get("alert_required"):
        tv_sender(
            build_country_unhealthy_message(
                country,
                int(decision.get("active_count") or 0),
                float(decision.get("circuit_open_until") or time.time()),
                tv_config["mentions"],
            )
        )
    if decision.get("circuit_open") or not decision.get("accepted"):
        registry.unregister(retry_key, pid=monitor_pid)
        return {
            "success": True,
            "status": "country_circuit_open",
            "active_count": decision.get("active_count", 0),
        }

    try:
        return auto_retry_runner(
            alert=alert,
            ds_token=ds_token,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            state_file=state_file,
            tv_sender=tv_sender,
            monitor_guard=lambda: registry.heartbeat(retry_key, pid=monitor_pid),
        )
    finally:
        registry.unregister(retry_key, pid=monitor_pid)


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

    with retry_lock(state_file, alert["retry_key"]) as acquired:
        if not acquired:
            result = {
                "success": True,
                "status": "already_running",
                "instance_id": alert["instance_id"],
                "retry_key": alert["retry_key"],
            }
        else:
            result = run_registered_auto_retry(
                alert=alert,
                ds_token=ds_token,
                max_attempts=args.max_attempts,
                retry_delay_seconds=args.retry_delay_seconds,
                state_file=state_file,
                request_id=args.request_id,
            )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
