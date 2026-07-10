#!/usr/bin/env python3
"""
Probe the target DolphinScheduler cluster to determine which API style is
available for workflow definition lookup, instance lookup, and start calls.

Run this on the server that can reach the target DS cluster.
"""

import json
import sys
from pathlib import Path
import argparse
from urllib.parse import urlencode
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import auto_load_env  # noqa: F401
from config.config import DS_CONFIG


DS_BASE = DS_CONFIG["base_url"].rstrip("/")
DS_TOKEN = DS_CONFIG["token"]
PROJECT_CODE = DS_CONFIG["project_code"]
ENVIRONMENT_CODE = DS_CONFIG["environment_code"]
TENANT_CODE = DS_CONFIG["tenant_code"]


def ds_api_get(endpoint):
    url = f"{DS_BASE}{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("token", DS_TOKEN)
    req.add_header("Accept", "application/json, text/plain, */*")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            text = response.read().decode("utf-8")
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                return False, {}, f"non-json response: {text[:200]}"
            return result.get("code") == 0, result.get("data", {}), result.get("msg", "")
    except Exception as exc:
        return False, {}, str(exc)


def ds_api_post(endpoint, data):
    url = f"{DS_BASE}{endpoint}"
    encoded = urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    req.add_header("token", DS_TOKEN)
    req.add_header("Accept", "application/json, text/plain, */*")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            text = response.read().decode("utf-8")
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                return False, {}, f"non-json response: {text[:200]}"
            return result.get("code") == 0, result, result.get("msg", "")
    except Exception as exc:
        return False, {}, str(exc)


def probe_definition_style():
    results = []
    for style in ("workflow-definition", "process-definition"):
        endpoint = f"/projects/{PROJECT_CODE}/{style}?pageNo=1&pageSize=5"
        success, data, msg = ds_api_get(endpoint)
        total_list = data.get("totalList", []) if isinstance(data, dict) else []
        first_code = total_list[0].get("code") if total_list else None
        results.append(
            {
                "style": style,
                "endpoint": endpoint,
                "success": success,
                "msg": msg,
                "count": len(total_list),
                "first_code": first_code,
            }
        )
    return results


def probe_instance_style():
    results = []
    for style in ("workflow-instances", "process-instances"):
        endpoint = f"/projects/{PROJECT_CODE}/{style}?pageNo=1&pageSize=5&stateType=RUNNING_EXECUTION"
        success, data, msg = ds_api_get(endpoint)
        total_list = data.get("totalList", []) if isinstance(data, dict) else []
        first_instance = total_list[0] if total_list else {}
        results.append(
            {
                "style": style,
                "endpoint": endpoint,
                "success": success,
                "msg": msg,
                "count": len(total_list),
                "first_instance_id": first_instance.get("id"),
                "first_instance_state": first_instance.get("state"),
                "first_definition_code": first_instance.get("processDefinitionCode")
                or first_instance.get("workflowDefinitionCode")
                or first_instance.get("definitionCode"),
            }
        )
    return results


def probe_instance_detail(instance_id):
    detail_results = []
    for style in ("process-instances", "workflow-instances"):
        endpoint = f"/projects/{PROJECT_CODE}/{style}/{instance_id}"
        success, data, msg = ds_api_get(endpoint)
        detail_results.append(
            {
                "style": style,
                "endpoint": endpoint,
                "success": success,
                "msg": msg,
                "state": data.get("state") if isinstance(data, dict) else None,
                "definition_code": (
                    data.get("processDefinitionCode")
                    or data.get("workflowDefinitionCode")
                    or data.get("definitionCode")
                ) if isinstance(data, dict) else None,
                "start_time": data.get("startTime") if isinstance(data, dict) else None,
            }
        )

    list_matches = []
    for state_type in ("RUNNING_EXECUTION", "SUCCESS", "FAILURE", "READY_STOP", "ALL", None):
        suffix = "?pageNo=1&pageSize=20"
        if state_type:
            suffix += f"&stateType={state_type}"
        endpoint = f"/projects/{PROJECT_CODE}/process-instances{suffix}"
        success, data, msg = ds_api_get(endpoint)
        total_list = data.get("totalList", []) if isinstance(data, dict) else []
        match = next((item for item in total_list if str(item.get("id")) == str(instance_id)), None)
        list_matches.append(
            {
                "state_type": state_type or "NONE",
                "endpoint": endpoint,
                "success": success,
                "msg": msg,
                "visible_count": len(total_list),
                "matched": bool(match),
                "matched_state": match.get("state") if match else None,
                "matched_definition_code": (
                    match.get("processDefinitionCode")
                    or match.get("workflowDefinitionCode")
                    or match.get("definitionCode")
                ) if match else None,
            }
        )

    return {
        "instance_id": instance_id,
        "detail_results": detail_results,
        "list_matches": list_matches,
    }


def probe_start_modes():
    definition_results = probe_definition_style()
    candidate_code = None
    for item in definition_results:
        if item["first_code"]:
            candidate_code = item["first_code"]
            break

    if not candidate_code:
        return {
            "candidate_workflow_code": None,
            "attempts": [],
            "note": "No workflow code available from definition list; cannot probe start API safely.",
        }

    attempts = []
    for endpoint_name, code_field in (
        ("start-process-instance", "processDefinitionCode"),
        ("start-workflow-instance", "workflowDefinitionCode"),
    ):
        payload = {
            code_field: candidate_code,
            "failureStrategy": "CONTINUE",
            "warningType": "NONE",
            "warningGroupId": 0,
            "execType": "START_PROCESS",
            "taskDependType": "TASK_POST",
            "environmentCode": ENVIRONMENT_CODE,
            "tenantCode": TENANT_CODE,
            "dryRun": 1,
            "scheduleTime": "" if endpoint_name == "start-process-instance" else "",
        }
        endpoint = f"/projects/{PROJECT_CODE}/executors/{endpoint_name}"
        success, data, msg = ds_api_post(endpoint, payload)
        attempts.append(
            {
                "endpoint": endpoint,
                "code_field": code_field,
                "success": success,
                "msg": msg,
                "response_data": data.get("data") if isinstance(data, dict) else None,
            }
        )

    return {
        "candidate_workflow_code": candidate_code,
        "attempts": attempts,
    }


def main():
    parser = argparse.ArgumentParser(description="Probe DolphinScheduler API mode")
    parser.add_argument(
        "--instance-id",
        help="Optional: probe detail and list visibility for a known process instance id",
    )
    args = parser.parse_args()

    report = {
        "base_url": DS_BASE,
        "project_code": PROJECT_CODE,
        "definition_style_probe": probe_definition_style(),
        "instance_style_probe": probe_instance_style(),
        "start_mode_probe": probe_start_modes(),
    }
    if args.instance_id:
        report["instance_detail_probe"] = probe_instance_detail(args.instance_id)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
