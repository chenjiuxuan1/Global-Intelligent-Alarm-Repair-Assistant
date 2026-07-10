#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取 DolphinScheduler 项目中引用 .sh 文件的任务清单。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]
LOCAL_CONFIG_DIR = PROJECT_ROOT / "config"

for extra_path in ("/home/node/.openclaw/workspace", str(LOCAL_CONFIG_DIR)):
    if extra_path not in sys.path:
        sys.path.insert(0, extra_path)

try:
    import auto_load_env  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    auto_load_env = None


DS_BASE_URL = os.environ.get("DS_BASE_URL", "http://127.0.0.1:12345/dolphinscheduler").rstrip("/")
DS_TOKEN = os.environ.get("DS_TOKEN", "")
DEFAULT_OUTPUT = PROJECT_ROOT / "sql_export" / "all_projects_sh_usage.csv"
SHELL_PATTERN = re.compile(r"([/\w\.-]+\.sh)\b", re.IGNORECASE)


def ds_api_get(endpoint: str) -> Tuple[bool, object]:
    url = f"{DS_BASE_URL}{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("token", DS_TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)

    if result.get("code") == 0:
        return True, result.get("data", {})
    return False, result.get("msg", "Unknown error")


def get_project_list() -> List[Dict[str, object]]:
    success, data = ds_api_get("/projects?pageNo=1&pageSize=200")
    if not success:
        raise RuntimeError(f"获取项目列表失败: {data}")
    return list((data or {}).get("totalList", []))


def resolve_project_codes(project_names: Iterable[str]) -> List[Tuple[str, str]]:
    projects = get_project_list()
    lookup = {str(item.get("name", "")): str(item.get("code", "")) for item in projects}
    resolved = []
    for name in project_names:
        code = lookup.get(name)
        if not code:
            raise ValueError(f"未找到项目名为 {name} 的项目")
        resolved.append((name, code))
    return resolved


def get_project_workflows(project_code: str) -> List[Dict[str, object]]:
    all_workflows = []
    page_no = 1
    while True:
        success, data = ds_api_get(
            f"/projects/{project_code}/process-definition?pageNo={page_no}&pageSize=100"
        )
        if not success:
            raise RuntimeError(f"获取工作流列表失败: {data}")
        workflows = list((data or {}).get("totalList", []) or [])
        total = int((data or {}).get("total", len(workflows)) or 0)
        if not workflows:
            break
        all_workflows.extend(workflows)
        if len(all_workflows) >= total:
            break
        page_no += 1
    return all_workflows


def get_workflow_detail(project_code: str, workflow_code: str) -> Dict[str, object]:
    success, data = ds_api_get(f"/projects/{project_code}/process-definition/{workflow_code}")
    if not success:
        raise RuntimeError(f"获取工作流详情失败: {data}")
    return data if isinstance(data, dict) else {}


def get_schedule_map(project_code: str) -> Dict[str, Dict[str, object]]:
    success, data = ds_api_get(f"/projects/{project_code}/schedules")
    if not success or not isinstance(data, dict):
        return {}
    schedule_map = {}
    for schedule in data.get("totalList", []) or []:
        code = str(schedule.get("processDefinitionCode", ""))
        if code:
            schedule_map[code] = {
                "schedule_status": str(schedule.get("releaseState", "NONE")),
                "schedule_cron": str(schedule.get("crontab", "")),
            }
    return schedule_map


def normalize_task_params(task_params: object) -> Dict[str, object]:
    if isinstance(task_params, str):
        try:
            task_params = json.loads(task_params)
        except json.JSONDecodeError:
            task_params = {}
    return task_params if isinstance(task_params, dict) else {}


def extract_sh_references_from_task(task: Dict[str, object]) -> List[Dict[str, str]]:
    task_params = normalize_task_params(task.get("taskParams", {}))
    results: List[Dict[str, str]] = []
    seen = set()

    for resource in task_params.get("resourceList", []) or []:
        full_name = str((resource or {}).get("fullName", ""))
        if full_name.lower().endswith(".sh") and full_name not in seen:
            seen.add(full_name)
            results.append({"reference_type": "resourceList", "script_path": full_name})

    raw_script = str(task_params.get("rawScript", ""))
    for match in SHELL_PATTERN.findall(raw_script):
        if match not in seen:
            seen.add(match)
            results.append({"reference_type": "rawScript", "script_path": match})

    for key, value in task_params.items():
        if not isinstance(value, str) or key == "rawScript":
            continue
        for match in SHELL_PATTERN.findall(value):
            if match not in seen:
                seen.add(match)
                results.append({"reference_type": f"param.{key}", "script_path": match})

    return results


def build_workflow_sh_rows(
    project_name: str,
    project_code: str,
    workflow: Dict[str, object],
    detail: Dict[str, object],
    schedule_map: Dict[str, Dict[str, object]],
) -> List[Dict[str, object]]:
    rows = []
    schedule_info = schedule_map.get(str(workflow.get("code", "")), {})
    for task in detail.get("taskDefinitionList", []) or []:
        if not isinstance(task, dict):
            continue
        refs = extract_sh_references_from_task(task)
        for ref in refs:
            rows.append(
                {
                    "project_name": project_name,
                    "project_code": project_code,
                    "workflow_name": workflow.get("name", ""),
                    "workflow_code": workflow.get("code", ""),
                    "workflow_release_state": workflow.get("releaseState", ""),
                    "schedule_status": schedule_info.get("schedule_status", "NONE"),
                    "schedule_cron": schedule_info.get("schedule_cron", ""),
                    "task_name": task.get("name", ""),
                    "task_code": task.get("code", ""),
                    "task_type": task.get("taskType", ""),
                    "reference_type": ref["reference_type"],
                    "script_path": ref["script_path"],
                }
            )
    return rows


def write_csv(rows: List[Dict[str, object]], output_path: str) -> None:
    fieldnames = [
        "project_name",
        "project_code",
        "workflow_name",
        "workflow_code",
        "workflow_release_state",
        "schedule_status",
        "schedule_cron",
        "task_name",
        "task_code",
        "task_type",
        "reference_type",
        "script_path",
    ]
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_projects(project_names: List[str], output_path: str) -> Tuple[int, int]:
    all_rows: List[Dict[str, object]] = []
    resolved = resolve_project_codes(project_names)
    for project_name, project_code in resolved:
        workflows = get_project_workflows(project_code)
        schedule_map = get_schedule_map(project_code)
        for workflow in workflows:
            detail = get_workflow_detail(project_code, str(workflow.get("code", "")))
            all_rows.extend(
                build_workflow_sh_rows(project_name, project_code, workflow, detail, schedule_map)
            )
    write_csv(all_rows, output_path)
    return len(resolved), len(all_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="提取 DS 项目中引用 .sh 文件的任务清单")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 CSV 路径")
    parser.add_argument("projects", nargs="+", help="项目名列表")
    args = parser.parse_args()

    if not DS_TOKEN:
        print("❌ 错误: DS_TOKEN 环境变量未设置")
        return

    try:
        project_count, row_count = export_projects(args.projects, args.output)
    except Exception as exc:
        print(f"❌ 导出失败: {exc}")
        return

    print(f"✅ 已处理 {project_count} 个项目")
    print(f"✅ 共导出 {row_count} 条 .sh 使用记录")
    print(f"📄 输出文件: {args.output}")


if __name__ == "__main__":
    main()
