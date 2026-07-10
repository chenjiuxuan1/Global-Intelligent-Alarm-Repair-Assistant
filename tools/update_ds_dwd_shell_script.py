#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量替换指定 DS 工作流中任务的 SHELL 脚本内容。

默认只预览变更；加 --apply 才会调用更新接口。
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


CURRENT_FILE = Path(__file__).resolve()
TOOLS_DIR = CURRENT_FILE.parent

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from fill_ds_workflow_resources import (  # noqa: E402
    DEFAULT_PROJECT_NAME,
    DEFAULT_WORKFLOW_NAME,
    DS_TOKEN,
    build_task_update_payload,
    ds_api_get,
    find_upstream_codes,
    get_task_detail,
    get_workflow_detail,
    normalize_task_params,
    release_task,
    resolve_project_code,
    resolve_workflow,
    update_task_with_upstream,
)


OLD_SCRIPT = 'python3 $WATTREL_HOME/console.py etl --table=${table} --args="v_start_dt=${dt}"'
NEW_SCRIPT = 'python3 $WATTREL2_HOME/console.py etl --table=${table} --args="${args}"'
DEFAULT_ENVIRONMENT_NAME = "dw_platform"


def apply_replacements(value: str, replacements: Iterable[Tuple[str, str]]) -> str:
    result = value
    for old, new in replacements:
        if old:
            result = result.replace(old, new)
    return result


def get_environment_list() -> List[Dict[str, object]]:
    success, data = ds_api_get("/environment/list-paging?pageNo=1&pageSize=200&searchVal=")
    if not success:
        raise RuntimeError(f"获取环境列表失败: {data}")
    return list((data or {}).get("totalList", []) or [])


def pick_environment_code(
    environment_list: Iterable[Dict[str, object]],
    environment_name: str,
) -> int:
    for environment in environment_list:
        if str(environment.get("name", "")).strip() == environment_name:
            return int(environment.get("code"))
    raise ValueError(f"未找到环境 {environment_name}")


def plan_script_updates(
    task_definition_list: Iterable[Dict[str, object]],
    old_script: str,
    new_script: str,
    target_environment_code: int | None = None,
    replace_all_shell_scripts: bool = False,
    raw_script_replacements: Iterable[Tuple[str, str]] = (),
    resource_replacements: Iterable[Tuple[str, str]] = (),
    target_task_names: set[str] | None = None,
) -> Tuple[List[Dict[str, object]], List[Dict[str, str]]]:
    updated_tasks: List[Dict[str, object]] = []
    changes: List[Dict[str, str]] = []

    for task in task_definition_list:
        cloned = copy.deepcopy(task)
        task_name = str(cloned.get("name", "")).strip()
        task_code = str(cloned.get("code", ""))
        task_type = str(cloned.get("taskType", "")).upper()
        task_params = normalize_task_params(cloned.get("taskParams", {}))
        raw_script = str(task_params.get("rawScript", ""))

        if target_task_names and task_name not in target_task_names:
            cloned["taskParams"] = task_params
            updated_tasks.append(cloned)
            continue

        script_changed = False
        resources_changed = False
        environment_changed = False
        old_environment_code = cloned.get("environmentCode")

        if task_type == "SHELL" and (replace_all_shell_scripts or raw_script == old_script):
            task_params["rawScript"] = new_script
            script_changed = True

        rewritten_script = apply_replacements(str(task_params.get("rawScript", "")), raw_script_replacements)
        if rewritten_script != str(task_params.get("rawScript", "")):
            task_params["rawScript"] = rewritten_script
            script_changed = True

        resource_list = task_params.get("resourceList", []) or []
        rewritten_resources = []
        for item in resource_list:
            entry = copy.deepcopy(item) if isinstance(item, dict) else {}
            original_name = str(entry.get("resourceName", ""))
            updated_name = apply_replacements(original_name, resource_replacements)
            if updated_name != original_name:
                resources_changed = True
            entry["resourceName"] = updated_name
            rewritten_resources.append(entry)
        if rewritten_resources:
            task_params["resourceList"] = rewritten_resources

        if target_environment_code is not None and cloned.get("environmentCode") != target_environment_code:
            cloned["environmentCode"] = target_environment_code
            environment_changed = True

        if script_changed or resources_changed or environment_changed:
            changes.append(
                {
                    "task_name": task_name,
                    "task_code": task_code,
                    "old_script": raw_script,
                    "new_script": str(task_params.get("rawScript", "")),
                    "old_environment_code": "" if old_environment_code is None else str(old_environment_code),
                    "new_environment_code": "" if target_environment_code is None else str(target_environment_code),
                }
            )

        cloned["taskParams"] = task_params
        updated_tasks.append(cloned)

    return updated_tasks, changes


def main() -> None:
    parser = argparse.ArgumentParser(description="批量替换 DS 工作流中的 SHELL 脚本")
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME, help="项目名")
    parser.add_argument("--workflow-name", default=DEFAULT_WORKFLOW_NAME, help="工作流名")
    parser.add_argument("--old-script", default=OLD_SCRIPT, help="原始脚本内容")
    parser.add_argument("--new-script", default=NEW_SCRIPT, help="新的脚本内容")
    parser.add_argument(
        "--environment-name",
        default=DEFAULT_ENVIRONMENT_NAME,
        help="目标环境名，如 dw_platform",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际提交更新；默认仅 dry-run 预览",
    )
    parser.add_argument(
        "--replace-all-shell-scripts",
        action="store_true",
        help="忽略旧脚本文本是否完全匹配，直接统一替换所有 SHELL 任务脚本",
    )
    parser.add_argument(
        "--raw-script-replace",
        action="append",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=[],
        help="对 rawScript 做字符串替换，可重复传入多次",
    )
    parser.add_argument(
        "--resource-replace",
        action="append",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=[],
        help="对 resourceList.resourceName 做字符串替换，可重复传入多次",
    )
    parser.add_argument(
        "--task-name",
        action="append",
        default=[],
        help="只处理指定任务名，可重复传入多次",
    )
    args = parser.parse_args()

    if not DS_TOKEN:
        print("❌ 错误: DS_TOKEN 环境变量未设置")
        return

    project_code = resolve_project_code(args.project_name)
    workflow = resolve_workflow(project_code, args.workflow_name)
    workflow_code = str(workflow.get("code", ""))
    detail = get_workflow_detail(project_code, workflow_code)
    environment_code = pick_environment_code(get_environment_list(), args.environment_name)
    target_task_names = {name.strip() for name in args.task_name if name.strip()}
    updated_tasks, changes = plan_script_updates(
        detail.get("taskDefinitionList", []),
        args.old_script,
        args.new_script,
        target_environment_code=environment_code,
        replace_all_shell_scripts=args.replace_all_shell_scripts,
        raw_script_replacements=[(old, new) for old, new in args.raw_script_replace],
        resource_replacements=[(old, new) for old, new in args.resource_replace],
        target_task_names=target_task_names or None,
    )

    print(f"项目: {args.project_name} ({project_code})")
    print(f"工作流: {args.workflow_name} ({workflow_code})")
    print(f"目标环境: {args.environment_name} ({environment_code})")
    print(f"候选任务数: {len(list(detail.get('taskDefinitionList', []) or []))}")
    if target_task_names:
        print(f"指定任务: {', '.join(sorted(target_task_names))}")
    print(f"待更新任务数: {len(changes)}")

    for change in changes:
        print(
            f"- {change['task_name']} ({change['task_code']}) "
            f"script: {change['old_script']} -> {change['new_script']} ; "
            f"env: {change['old_environment_code']} -> {change['new_environment_code']}"
        )

    if not args.apply:
        print("ℹ️ 当前为 dry-run，未提交到 DolphinScheduler")
        return

    if not changes:
        print("ℹ️ 没有需要更新脚本或环境的任务")
        return

    task_by_code = {
        str(task.get("code", "")): task for task in updated_tasks if str(task.get("code", ""))
    }
    all_success = True

    for change in changes:
        task_code = change["task_code"]
        task_name = change["task_name"]
        task_detail = get_task_detail(project_code, task_code)
        original_flag = str(task_detail.get("flag", "YES")).upper()

        if original_flag == "YES":
            released, release_msg = release_task(project_code, task_code, "OFFLINE")
            if not released:
                all_success = False
                print(f"❌ 下线失败: {task_name} ({task_code})")
                print(release_msg)
                continue

        payload = build_task_update_payload(task_by_code[task_code], workflow_code)
        upstream_codes = find_upstream_codes(task_code, detail.get("processTaskRelationList", []))
        success, data, endpoint = update_task_with_upstream(
            project_code,
            task_code,
            payload,
            upstream_codes,
        )
        if not success:
            all_success = False
            print(f"❌ 提交失败: {task_name} ({task_code})")
            print(endpoint)
            print(data)
        else:
            print(f"✅ 已更新脚本和环境: {task_name} ({task_code})")

        if original_flag == "YES":
            restored, restore_msg = release_task(project_code, task_code, "ONLINE")
            if not restored:
                all_success = False
                print(f"❌ 恢复上线失败: {task_name} ({task_code})")
                print(restore_msg)

    if all_success:
        print("✅ 本次脚本与环境更新已全部完成")


if __name__ == "__main__":
    main()
