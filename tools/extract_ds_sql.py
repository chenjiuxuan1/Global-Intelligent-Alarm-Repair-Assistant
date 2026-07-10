#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DolphinScheduler 工作流 SQL 提取工具

能力：
1. 通过 DS API 拉取指定项目下的工作流和任务定义
2. 仅导出上线工作流中的 SQL 节点
3. 将 SQL 按“库名/节点名.sql”落盘
4. 额外输出一份可直接用 Excel 打开的状态清单 CSV
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
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


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
SQL_TASK_TYPES = {"SQL", "SQLODT", "SQLPRESTO", "SQLFLINK", "SQLSPARK"}
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "sql_export"
STATUS_HEADERS = [
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
    "database_name",
    "sql_source",
    "sql_length",
    "output_file",
]


def ds_api_get(endpoint: str) -> Tuple[bool, object]:
    """发送 GET 请求到 DS API。"""
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


def sanitize_name(name: str, fallback: str) -> str:
    cleaned = "".join(ch for ch in (name or "") if ch.isalnum() or ch in ("_", "-", ".", " ")).strip()
    cleaned = cleaned.replace(" ", "_")
    return cleaned or fallback


def filter_online_workflows(workflows: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    return [
        workflow
        for workflow in workflows
        if str(workflow.get("releaseState", "")).upper() == "ONLINE"
    ]


def detect_target_database(sql_content: str) -> str:
    """
    优先识别写入目标库；如果只命中一个库则返回该库，多个库返回 mixed。
    完全识别不到则返回 unknown_db。
    """
    sql_text = sql_content or ""
    normalized = re.sub(r"\s+", " ", sql_text.lower())

    target_patterns = [
        r"\binsert\s+(?:overwrite|into)\s+table\s+([a-zA-Z_][\w]*)\.[a-zA-Z_][\w]*",
        r"\btruncate\s+table\s+([a-zA-Z_][\w]*)\.[a-zA-Z_][\w]*",
        r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?([a-zA-Z_][\w]*)\.[a-zA-Z_][\w]*",
    ]
    for pattern in target_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower()

    db_names = {
        match.group(1).lower()
        for match in re.finditer(r"\b([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\b", normalized)
        if match.group(1).lower() not in {"${", "#{", "tmp"}
    }
    if not db_names:
        return "unknown_db"
    if len(db_names) == 1:
        return next(iter(db_names))
    return "mixed"


def get_sql_from_task_params(task_params: object) -> Tuple[str, str]:
    if isinstance(task_params, str):
        try:
            task_params = json.loads(task_params)
        except json.JSONDecodeError:
            task_params = {}
    if not isinstance(task_params, dict):
        return "", "none"

    for key in ("sql", "rawScript"):
        value = task_params.get(key, "")
        if isinstance(value, str) and value.strip():
            return value.strip(), key
    return "", "none"


def extract_sql_from_workflow(workflow_detail: Dict[str, object]) -> List[Dict[str, object]]:
    """从工作流详情中提取 SQL 代码。"""
    sql_tasks: List[Dict[str, object]] = []

    process_def = workflow_detail.get("processDefinition", {}) or {}
    task_definitions = workflow_detail.get("taskDefinitionList", []) or []

    workflow_name = str(process_def.get("name", "Unknown"))
    workflow_code = str(process_def.get("code", ""))

    for task in task_definitions:
        if not isinstance(task, dict):
            continue

        task_type = str(task.get("taskType", ""))
        if task_type.upper() not in SQL_TASK_TYPES:
            continue

        task_params = task.get("taskParams", {})
        sql_content, sql_source = get_sql_from_task_params(task_params)
        if not sql_content:
            continue

        database_name = detect_target_database(sql_content)
        datasource = ""
        if isinstance(task_params, dict):
            datasource = str(task_params.get("datasource", ""))

        sql_tasks.append(
            {
                "workflow_name": workflow_name,
                "workflow_code": workflow_code,
                "task_name": str(task.get("name", "")),
                "task_code": str(task.get("code", "")),
                "task_type": task_type,
                "datasource": datasource,
                "sql": sql_content,
                "sql_source": sql_source,
                "database_name": database_name,
            }
        )

    return sql_tasks


def save_sql_task(task: Dict[str, object], output_dir: str) -> str:
    database_name = sanitize_name(str(task.get("database_name", "unknown_db")), "unknown_db")
    task_name = sanitize_name(str(task.get("task_name", "unnamed_task")), "unnamed_task")
    target_dir = Path(output_dir) / database_name
    target_dir.mkdir(parents=True, exist_ok=True)

    file_path = target_dir / f"{task_name}.sql"
    header = (
        f"-- Workflow: {task.get('workflow_name', '')}\n"
        f"-- Workflow Code: {task.get('workflow_code', '')}\n"
        f"-- Task: {task.get('task_name', '')}\n"
        f"-- Task Code: {task.get('task_code', '')}\n"
        f"-- Task Type: {task.get('task_type', '')}\n"
        f"-- Database Folder: {database_name}\n"
        f"-- SQL Source: {task.get('sql_source', '')}\n"
        f"-- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"-- {'=' * 60}\n\n"
    )
    with open(file_path, "w", encoding="utf-8") as handle:
        handle.write(header)
        handle.write(str(task.get("sql", "")).strip())
        handle.write("\n")
    return str(file_path)


def write_status_report(rows: List[Dict[str, object]], report_path: str) -> None:
    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STATUS_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in STATUS_HEADERS})


def get_project_list() -> List[Dict[str, object]]:
    success, data = ds_api_get("/projects?pageNo=1&pageSize=100")
    if not success:
        raise RuntimeError(f"获取项目列表失败: {data}")
    if isinstance(data, dict):
        return list(data.get("totalList", []))
    return []


def resolve_project(project_code: Optional[str] = None, project_name: Optional[str] = None) -> Tuple[str, str]:
    if project_code and project_name:
        return str(project_code), project_name

    if project_code and not project_name:
        success, data = ds_api_get(f"/projects/{project_code}")
        if success and isinstance(data, dict):
            return str(project_code), str(data.get("name", project_code))
        return str(project_code), str(project_code)

    if not project_name:
        raise ValueError("必须提供 project_code 或 project_name")

    projects = get_project_list()
    for project in projects:
        if str(project.get("name", "")).strip().lower() == project_name.strip().lower():
            return str(project.get("code", "")), str(project.get("name", project_name))
    raise ValueError(f"未找到项目名为 {project_name} 的项目")


def get_project_workflows(project_code: str) -> List[Dict[str, object]]:
    """获取项目下的所有工作流列表。"""
    all_workflows: List[Dict[str, object]] = []
    page_no = 1
    page_size = 100

    while True:
        success, data = ds_api_get(
            f"/projects/{project_code}/process-definition?pageNo={page_no}&pageSize={page_size}"
        )
        if not success:
            raise RuntimeError(f"获取工作流列表失败: {data}")
        if not isinstance(data, dict):
            break

        workflows = data.get("totalList", []) or []
        total = int(data.get("total", len(workflows)) or 0)
        if not workflows:
            break
        all_workflows.extend(workflows)
        if len(all_workflows) >= total:
            break
        page_no += 1

    return all_workflows


def get_workflow_detail(project_code: str, workflow_code: str) -> Optional[Dict[str, object]]:
    success, data = ds_api_get(f"/projects/{project_code}/process-definition/{workflow_code}")
    if not success:
        print(f"❌ 获取工作流详情失败: {data}")
        return None
    if not isinstance(data, dict):
        return None
    return data


def get_schedule_map(project_code: str) -> Dict[str, Dict[str, object]]:
    success, data = ds_api_get(f"/projects/{project_code}/schedules")
    if not success or not isinstance(data, dict):
        return {}

    schedule_map: Dict[str, Dict[str, object]] = {}
    for schedule in data.get("totalList", []) or []:
        process_code = str(schedule.get("processDefinitionCode", ""))
        if not process_code:
            continue
        schedule_map[process_code] = {
            "schedule_status": str(schedule.get("releaseState", "NONE")),
            "schedule_cron": str(schedule.get("crontab", "")),
            "schedule_id": str(schedule.get("id", "")),
        }
    return schedule_map


def build_status_row(
    project_name: str,
    project_code: str,
    workflow: Dict[str, object],
    task: Dict[str, object],
    schedule_info: Dict[str, object],
    output_file: str,
    output_root: str,
) -> Dict[str, object]:
    relative_output = os.path.relpath(output_file, output_root)
    return {
        "project_name": project_name,
        "project_code": project_code,
        "workflow_name": workflow.get("name", ""),
        "workflow_code": workflow.get("code", ""),
        "workflow_release_state": workflow.get("releaseState", ""),
        "schedule_status": schedule_info.get("schedule_status", "NONE"),
        "schedule_cron": schedule_info.get("schedule_cron", ""),
        "task_name": task.get("task_name", ""),
        "task_code": task.get("task_code", ""),
        "task_type": task.get("task_type", ""),
        "database_name": task.get("database_name", ""),
        "sql_source": task.get("sql_source", ""),
        "sql_length": len(str(task.get("sql", ""))),
        "output_file": relative_output,
    }


def extract_project_sql(
    project_code: Optional[str] = None,
    project_name: Optional[str] = None,
    output_dir: Optional[str] = None,
    online_only: bool = True,
) -> Tuple[int, str, str]:
    resolved_project_code, resolved_project_name = resolve_project(project_code, project_name)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_ROOT / f"{resolved_project_name}_{timestamp}"
    root_dir.mkdir(parents=True, exist_ok=True)
    report_path = root_dir / "pre_extract_status.csv"

    print("=" * 70)
    print("🚀 开始提取项目 SQL")
    print(f"项目名称: {resolved_project_name}")
    print(f"项目 Code: {resolved_project_code}")
    print(f"DS 地址: {DS_BASE_URL}")
    print(f"输出目录: {root_dir}")
    print("=" * 70)
    print()

    workflows = get_project_workflows(resolved_project_code)
    total_workflows = len(workflows)
    print(f"📋 共获取到 {total_workflows} 个工作流")

    if online_only:
        workflows = filter_online_workflows(workflows)
        print(f"✅ 其中上线工作流 {len(workflows)} 个")

    if not workflows:
        print("⚠️ 没有可处理的工作流")
        write_status_report([], str(report_path))
        return 0, str(root_dir), str(report_path)

    schedule_map = get_schedule_map(resolved_project_code)
    all_status_rows: List[Dict[str, object]] = []
    exported_count = 0

    for index, workflow in enumerate(workflows, 1):
        workflow_name = str(workflow.get("name", "Unknown"))
        workflow_code = str(workflow.get("code", ""))
        print(f"[{index}/{len(workflows)}] 处理工作流: {workflow_name}")

        detail = get_workflow_detail(resolved_project_code, workflow_code)
        if not detail:
            print("    ⚠️ 跳过（获取详情失败）")
            continue

        sql_tasks = extract_sql_from_workflow(detail)
        if not sql_tasks:
            print("    ℹ️ 无 SQL 任务")
            continue

        schedule_info = schedule_map.get(
            workflow_code,
            {"schedule_status": "NONE", "schedule_cron": "", "schedule_id": ""},
        )

        print(f"    ✅ 找到 {len(sql_tasks)} 个 SQL 任务")
        for task in sql_tasks:
            output_file = save_sql_task(task, str(root_dir))
            all_status_rows.append(
                build_status_row(
                    resolved_project_name,
                    resolved_project_code,
                    workflow,
                    task,
                    schedule_info,
                    output_file,
                    str(root_dir),
                )
            )
            exported_count += 1
            print(f"       💾 已保存: {os.path.relpath(output_file, root_dir)}")
        print()

    write_status_report(all_status_rows, str(report_path))

    print("=" * 70)
    print("📊 提取完成统计")
    print("=" * 70)
    print(f"项目: {resolved_project_name}")
    print(f"工作流总数: {total_workflows}")
    print(f"处理工作流数: {len(workflows)}")
    print(f"SQL 任务总数: {exported_count}")
    print(f"输出目录: {root_dir}")
    print(f"状态清单: {report_path}")
    print("=" * 70)

    return exported_count, str(root_dir), str(report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="提取 DolphinScheduler 项目中的 SQL")
    parser.add_argument("project_code", nargs="?", help="项目 Code")
    parser.add_argument("--project-name", dest="project_name", help="项目名称，例如 DW_DM")
    parser.add_argument("--name", dest="project_name_alias", help="兼容旧参数，等同于 --project-name")
    parser.add_argument("--output", type=str, help="输出目录")
    parser.add_argument(
        "--include-offline",
        action="store_true",
        help="包含未上线工作流；默认只导出上线工作流",
    )
    args = parser.parse_args()

    project_name = args.project_name or args.project_name_alias
    if not DS_TOKEN:
        print("❌ 错误: DS_TOKEN 环境变量未设置")
        print("请执行: export DS_TOKEN='your_token'")
        return

    try:
        count, _, report_path = extract_project_sql(
            project_code=args.project_code,
            project_name=project_name,
            output_dir=args.output,
            online_only=not args.include_offline,
        )
    except Exception as exc:
        print(f"❌ 提取失败: {exc}")
        return

    if count > 0:
        print(f"\n✅ 成功提取 {count} 个 SQL 任务")
        print(f"📄 状态清单已生成: {report_path}")
    else:
        print("\n⚠️ 未提取到 SQL 任务")


if __name__ == "__main__":
    main()
