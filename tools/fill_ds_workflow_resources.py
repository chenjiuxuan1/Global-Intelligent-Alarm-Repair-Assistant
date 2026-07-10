#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为指定 DS 项目/工作流中的任务补齐 resourceList。

默认只预览变更；加 --apply 才会调用更新接口。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.parse
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
DEFAULT_PROJECT_NAME = "巴基斯坦-数仓工作流_new"
DEFAULT_WORKFLOW_NAME = "DWD"
DEFAULT_RESOURCE_ROOT = "deploy/resources/starrocks_workflow/dwd"
RESOURCE_PREFIX = "dolphinscheduler/resource"


def ds_api_request(
    method: str,
    endpoint: str,
    data: Dict[str, object] | None = None,
    query_mode: bool = False,
) -> Tuple[bool, object]:
    url = f"{DS_BASE_URL}{endpoint}"
    payload = None
    if data is not None:
        normalized = {
            key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list))
            else "" if value is None else str(value)
            for key, value in data.items()
        }
        encoded = urllib.parse.urlencode(normalized)
        if query_mode:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{encoded}"
        else:
            payload = encoded.encode("utf-8")

    req = urllib.request.Request(url, method=method.upper(), data=payload)
    req.add_header("token", DS_TOKEN)
    req.add_header("Accept", "application/json, text/plain, */*")
    if payload is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="ignore")
        return False, f"HTTP {exc.code}: {exc.reason} {message}".strip()
    except Exception as exc:
        return False, str(exc)

    if result.get("code") == 0:
        return True, result.get("data", {})
    return False, result.get("msg", "Unknown error")


def ds_api_get(endpoint: str) -> Tuple[bool, object]:
    return ds_api_request("GET", endpoint)


def ds_api_json_request(
    method: str,
    endpoint: str,
    data: Dict[str, object],
) -> Tuple[bool, object]:
    url = f"{DS_BASE_URL}{endpoint}"
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, method=method.upper(), data=payload)
    req.add_header("token", DS_TOKEN)
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="ignore")
        return False, f"HTTP {exc.code}: {exc.reason} {message}".strip()
    except Exception as exc:
        return False, str(exc)

    if result.get("code") == 0:
        return True, result.get("data", {})
    return False, result.get("msg", "Unknown error")


def normalize_task_params(task_params: object) -> Dict[str, object]:
    if isinstance(task_params, str):
        try:
            task_params = json.loads(task_params)
        except json.JSONDecodeError:
            task_params = {}
    return task_params if isinstance(task_params, dict) else {}


def prune_nones(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: prune_nones(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [prune_nones(item) for item in value]
    return value


def get_project_list() -> List[Dict[str, object]]:
    success, data = ds_api_get("/projects?pageNo=1&pageSize=200")
    if not success:
        raise RuntimeError(f"获取项目列表失败: {data}")
    return list((data or {}).get("totalList", []))


def resolve_project_code(project_name: str) -> str:
    for item in get_project_list():
        if str(item.get("name", "")) == project_name:
            return str(item.get("code", ""))
    raise ValueError(f"未找到项目名为 {project_name} 的项目")


def get_project_workflows(project_code: str) -> List[Dict[str, object]]:
    success, data = ds_api_get(f"/projects/{project_code}/process-definition?pageNo=1&pageSize=200")
    if not success:
        raise RuntimeError(f"获取工作流列表失败: {data}")
    return list((data or {}).get("totalList", []) or [])


def resolve_workflow(project_code: str, workflow_name: str) -> Dict[str, object]:
    for workflow in get_project_workflows(project_code):
        if str(workflow.get("name", "")) == workflow_name:
            return workflow
    raise ValueError(f"未找到工作流 {workflow_name}")


def get_workflow_detail(project_code: str, workflow_code: str) -> Dict[str, object]:
    success, data = ds_api_get(f"/projects/{project_code}/process-definition/{workflow_code}")
    if not success:
        raise RuntimeError(f"获取工作流详情失败: {data}")
    return data if isinstance(data, dict) else {}


def get_task_detail(project_code: str, task_code: str) -> Dict[str, object]:
    success, data = ds_api_get(f"/projects/{project_code}/task-definition/{task_code}")
    if not success:
        raise RuntimeError(f"获取任务详情失败: {data}")
    return dict(data or {})


def build_resource_path(task_name: str, resource_root: str) -> str:
    relative_path = f"{resource_root.rstrip('/')}/{task_name}/{task_name}.sql".lstrip("/")
    return f"{RESOURCE_PREFIX}/{relative_path}"


def prefix_resource_name(resource_name: str, resource_prefix: str) -> str:
    normalized_name = str(resource_name or "").strip()
    if not normalized_name:
        return ""

    normalized_prefix = resource_prefix.rstrip("/")
    display_marker = "dolphinscheduler/resources/"
    if display_marker in normalized_name:
        normalized_name = normalized_name.rsplit(display_marker, 1)[1]
        return f"{normalized_prefix}/{normalized_name.lstrip('/')}"
    if normalized_name.startswith("dolphinscheduler/resource/"):
        return normalized_name
    return f"{normalized_prefix}/{normalized_name.lstrip('/')}"


def plan_task_updates(
    task_definition_list: Iterable[Dict[str, object]],
    resource_root: str,
    overwrite_existing: bool = False,
    target_task_names: set[str] | None = None,
    reuse_existing_relative_paths: bool = False,
    resource_prefix: str = RESOURCE_PREFIX,
    resource_name_override: str | None = None,
) -> Tuple[List[Dict[str, object]], List[Dict[str, str]]]:
    updated_tasks: List[Dict[str, object]] = []
    changes: List[Dict[str, str]] = []

    for task in task_definition_list:
        cloned = copy.deepcopy(task)
        task_name = str(cloned.get("name", "")).strip()
        task_code = str(cloned.get("code", ""))
        task_params = normalize_task_params(cloned.get("taskParams", {}))
        resource_list = task_params.get("resourceList", []) or []
        if target_task_names and task_name not in target_task_names:
            cloned["taskParams"] = task_params
            updated_tasks.append(cloned)
            continue

        new_resource_list = None
        should_skip_fallback_rebuild = False
        if resource_list and reuse_existing_relative_paths:
            should_skip_fallback_rebuild = True
            rewritten_resources = []
            has_change = False
            old_resource_name = str((resource_list[0] or {}).get("resourceName", ""))
            for item in resource_list:
                entry = copy.deepcopy(item) if isinstance(item, dict) else {}
                original_name = str(entry.get("resourceName", ""))
                updated_name = prefix_resource_name(original_name, resource_prefix)
                if updated_name and updated_name != original_name:
                    has_change = True
                entry["resourceName"] = updated_name
                rewritten_resources.append(entry)
            if has_change:
                new_resource_list = rewritten_resources
                changes.append(
                    {
                        "task_name": task_name,
                        "task_code": task_code,
                        "old_resource_name": old_resource_name,
                        "resource_name": ", ".join(
                            str(item.get("resourceName", "")) for item in rewritten_resources
                        ),
                    }
                )

        if (
            new_resource_list is None
            and not should_skip_fallback_rebuild
            and task_name
            and (overwrite_existing or not resource_list)
        ):
            resource_name = (
                resource_name_override
                if resource_name_override
                else build_resource_path(task_name, resource_root)
            )
            new_resource_list = [{"resourceName": resource_name}]
            old_resource_name = ""
            if resource_list:
                old_resource_name = str((resource_list[0] or {}).get("resourceName", ""))
            changes.append(
                {
                    "task_name": task_name,
                    "task_code": task_code,
                    "old_resource_name": old_resource_name,
                    "resource_name": resource_name,
                }
            )

        if new_resource_list is not None:
            task_params["resourceList"] = new_resource_list

        cloned["taskParams"] = task_params
        updated_tasks.append(cloned)

    return updated_tasks, changes


def find_upstream_codes(
    task_code: str | int,
    process_task_relation_list: Iterable[Dict[str, object]],
) -> List[str]:
    normalized_task_code = str(task_code)
    upstream_codes: List[str] = []
    for relation in process_task_relation_list:
        if str(relation.get("postTaskCode", "")) != normalized_task_code:
            continue
        pre_task_code = str(relation.get("preTaskCode", "")).strip()
        if pre_task_code and pre_task_code != "0":
            upstream_codes.append(pre_task_code)
    return upstream_codes


def _task_definition_record(task: Dict[str, object]) -> Dict[str, object]:
    task_params = normalize_task_params(task.get("taskParams", {}))
    return prune_nones({
        "code": task.get("code"),
        "version": task.get("version", 1),
        "name": task.get("name", ""),
        "description": task.get("description", ""),
        "taskType": task.get("taskType", ""),
        "taskParams": json.dumps(task_params, ensure_ascii=False),
        "flag": task.get("flag", "YES"),
        "taskPriority": task.get("taskPriority", "MEDIUM"),
        "workerGroup": task.get("workerGroup", "default"),
        "environmentCode": task.get("environmentCode", -1),
        "failRetryTimes": task.get("failRetryTimes", 0),
        "failRetryInterval": task.get("failRetryInterval", 1),
        "timeoutFlag": task.get("timeoutFlag", "CLOSE"),
        "timeoutNotifyStrategy": task.get("timeoutNotifyStrategy"),
        "timeout": task.get("timeout", 0),
        "delayTime": task.get("delayTime", 0),
        "taskGroupId": task.get("taskGroupId", 0),
        "taskGroupPriority": task.get("taskGroupPriority", 0),
        "cpuQuota": task.get("cpuQuota", -1),
        "memoryMax": task.get("memoryMax", -1),
        "taskExecuteType": task.get("taskExecuteType", "BATCH"),
        "projectCode": task.get("projectCode"),
        "userId": task.get("userId"),
        "resourceIds": task.get("resourceIds"),
    })


def _task_relation_record(relation: Dict[str, object]) -> Dict[str, object]:
    condition_params = relation.get("conditionParams", {})
    return prune_nones({
        "name": relation.get("name", ""),
        "projectCode": relation.get("projectCode"),
        "processDefinitionCode": relation.get("processDefinitionCode"),
        "processDefinitionVersion": relation.get("processDefinitionVersion"),
        "preTaskCode": relation.get("preTaskCode", 0),
        "preTaskVersion": relation.get("preTaskVersion", 0),
        "postTaskCode": relation.get("postTaskCode", 0),
        "postTaskVersion": relation.get("postTaskVersion", 0),
        "conditionType": relation.get("conditionType", "NONE"),
        "conditionParams": json.dumps(condition_params, ensure_ascii=False),
    })


def build_update_payload(detail: Dict[str, object]) -> Dict[str, object]:
    process_definition = dict(detail.get("processDefinition", {}) or {})
    task_definition_list = list(detail.get("taskDefinitionList", []) or [])
    process_task_relation_list = list(detail.get("processTaskRelationList", []) or [])

    return prune_nones({
        "name": process_definition.get("name", ""),
        "description": process_definition.get("description", ""),
        "globalParams": process_definition.get("globalParams", "[]"),
        "locations": process_definition.get("locations", "[]"),
        "timeout": process_definition.get("timeout", 0),
        "executionType": process_definition.get("executionType", "PARALLEL"),
        "releaseState": process_definition.get("releaseState"),
        "otherParamsJson": process_definition.get("otherParamsJson"),
        "taskDefinitionJson": [_task_definition_record(task) for task in task_definition_list],
        "taskRelationJson": [
            _task_relation_record(relation) for relation in process_task_relation_list
        ],
    })


def build_task_update_payload(
    task: Dict[str, object],
    workflow_code: str | int,
) -> Dict[str, object]:
    task_params = normalize_task_params(task.get("taskParams", {}))
    return prune_nones({
        "workflowCode": int(workflow_code),
        "name": task.get("name", ""),
        "description": task.get("description", "") or "",
        "taskType": task.get("taskType", ""),
        "taskParams": json.dumps(task_params, ensure_ascii=False),
        "flag": task.get("flag", "YES"),
        "taskPriority": task.get("taskPriority", "MEDIUM"),
        "workerGroup": task.get("workerGroup", "default"),
        "environmentCode": task.get("environmentCode"),
        "failRetryTimes": task.get("failRetryTimes", 0),
        "failRetryInterval": task.get("failRetryInterval", 1),
        "timeout": task.get("timeout", 0),
        "timeoutFlag": task.get("timeoutFlag", "CLOSE"),
        "timeoutNotifyStrategy": task.get("timeoutNotifyStrategy"),
        "resourceIds": task.get("resourceIds", "") or "",
        "taskGroupId": task.get("taskGroupId", 0),
        "taskGroupPriority": task.get("taskGroupPriority", 0),
        "cpuQuota": task.get("cpuQuota", -1),
        "memoryMax": task.get("memoryMax", -1),
    })


def release_task(project_code: str, task_code: str, release_state: str) -> Tuple[bool, object]:
    endpoint = (
        f"/projects/{project_code}/task-definition/{task_code}/release"
        f"?{urllib.parse.urlencode({'releaseState': release_state})}"
    )
    return ds_api_request("POST", endpoint)


def update_task_with_upstream(
    project_code: str,
    task_code: str,
    payload: Dict[str, object],
    upstream_codes: Iterable[str],
) -> Tuple[bool, object, str]:
    query = urllib.parse.urlencode(
        {
            "taskDefinitionJsonObj": json.dumps(payload, ensure_ascii=False),
            "upstreamCodes": ",".join(upstream_codes),
        }
    )
    endpoint = f"/projects/{project_code}/task-definition/{task_code}/with-upstream?{query}"
    success, data = ds_api_request("PUT", endpoint)
    return success, data, endpoint


def main() -> None:
    parser = argparse.ArgumentParser(description="为 DS 工作流任务补齐 resourceList")
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME, help="项目名")
    parser.add_argument("--workflow-name", default=DEFAULT_WORKFLOW_NAME, help="工作流名")
    parser.add_argument(
        "--resource-root",
        default=DEFAULT_RESOURCE_ROOT,
        help="资源根目录，如 deploy/resources/starrocks_workflow/dwd",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际提交更新；默认仅 dry-run 预览",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="强制覆盖已有 resourceList，而不是只补空值",
    )
    parser.add_argument(
        "--task-name",
        action="append",
        default=[],
        help="只处理指定任务名，可重复传入多次",
    )
    parser.add_argument(
        "--reuse-existing-relative-paths",
        action="store_true",
        help="保留 resourceList 原有相对路径，只补完整前缀",
    )
    parser.add_argument(
        "--resource-prefix",
        default=RESOURCE_PREFIX,
        help="资源名前缀，如 dolphinscheduler/resource 或 dolphinscheduler/resources",
    )
    parser.add_argument(
        "--resource-name-override",
        default="",
        help="直接指定完整 resourceName，命中的任务统一使用这个资源",
    )
    args = parser.parse_args()

    if not DS_TOKEN:
        print("❌ 错误: DS_TOKEN 环境变量未设置")
        return

    project_code = resolve_project_code(args.project_name)
    workflow = resolve_workflow(project_code, args.workflow_name)
    workflow_code = str(workflow.get("code", ""))
    detail = get_workflow_detail(project_code, workflow_code)
    target_task_names = {name.strip() for name in args.task_name if name.strip()}
    updated_tasks, changes = plan_task_updates(
        detail.get("taskDefinitionList", []),
        args.resource_root,
        overwrite_existing=args.overwrite_existing,
        target_task_names=target_task_names or None,
        reuse_existing_relative_paths=args.reuse_existing_relative_paths,
        resource_prefix=args.resource_prefix,
        resource_name_override=args.resource_name_override.strip() or None,
    )

    print(f"项目: {args.project_name} ({project_code})")
    print(f"工作流: {args.workflow_name} ({workflow_code})")
    print(f"候选任务数: {len(list(detail.get('taskDefinitionList', []) or []))}")
    if target_task_names:
        print(f"指定任务: {', '.join(sorted(target_task_names))}")
    print(f"待补资源任务数: {len(changes)}")

    for change in changes:
        print(
            f"- {change['task_name']} ({change['task_code']}) -> {change['resource_name']}"
        )

    if not args.apply:
        print("ℹ️ 当前为 dry-run，未提交到 DolphinScheduler")
        return

    if not changes:
        print("ℹ️ 没有需要补充 resourceList 的任务")
        return

    changed_task_map = {item["task_code"]: item for item in changes}
    task_by_code = {
        str(task.get("code", "")): task for task in updated_tasks if str(task.get("code", ""))
    }
    all_success = True

    for task_code, change in changed_task_map.items():
        task_detail = get_task_detail(project_code, task_code)
        original_flag = str(task_detail.get("flag", "YES")).upper()
        if original_flag == "YES":
            released, release_msg = release_task(project_code, task_code, "OFFLINE")
            if not released:
                all_success = False
                print(f"❌ 下线失败: {change['task_name']} ({task_code})")
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
            print(f"❌ 提交失败: {change['task_name']} ({task_code})")
            print(endpoint)
            print(data)
        else:
            print(f"✅ 已提交更新: {change['task_name']} ({task_code})")

        if original_flag == "YES":
            restored, restore_msg = release_task(project_code, task_code, "ONLINE")
            if not restored:
                all_success = False
                print(f"❌ 恢复上线失败: {change['task_name']} ({task_code})")
                print(restore_msg)

    if all_success:
        print("✅ 本次任务资源补齐已全部完成")


if __name__ == "__main__":
    main()
