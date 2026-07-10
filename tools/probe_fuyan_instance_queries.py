#!/usr/bin/env python3
"""
Probe fuyan workflow instance visibility for Indonesian DS clusters.

Use this after a fuyan workflow has been started. The script checks:
1. Which project code should be used for each configured fuyan workflow.
2. Whether the returned start response id is queryable by detail APIs.
3. Whether the real instance is visible in list APIs under different state types/pages.
4. Whether matching by workflow code + launched_at can recover the real instance.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import auto_load_env  # noqa: F401
from config.config import DS_CONFIG, FUYAN_WORKFLOWS
from core import repair_strict_7step as repair


def get_fuyan_candidates():
    candidates = []
    for workflow in FUYAN_WORKFLOWS:
        candidates.append(
            {
                "name": repair.get_fuyan_name(workflow),
                "workflow_code": repair.get_fuyan_code(workflow),
                "project_code": repair.get_fuyan_project_code(workflow),
                "level": workflow.get("level"),
            }
        )
    return candidates


def probe_list_pages(project_code, instance_id, workflow_code, launched_at, page_size=100, max_pages=5):
    probes = []
    state_types = repair._get_instance_state_types_for_search(include_all=True)
    for style in repair._get_instance_list_styles():
        for state_type in state_types:
            found = None
            pages = []
            for page_no in range(1, max_pages + 1):
                endpoints = repair._build_instance_list_endpoints(
                    project_code=project_code,
                    state_type=state_type,
                    page_no=page_no,
                    page_size=page_size,
                )
                # Only probe the current style so we can see where visibility differs.
                endpoints = [endpoint for endpoint in endpoints if f"/{style}" in endpoint]
                if not endpoints:
                    continue
                endpoint = endpoints[0]
                success, data, msg = repair.ds_api_get(endpoint)
                total_list = data.get("totalList", []) if isinstance(data, dict) else []
                match_by_id = next((item for item in total_list if str(item.get("id")) == str(instance_id)), None)
                match_by_workflow = next(
                    (
                        item
                        for item in total_list
                        if str(
                            item.get("processDefinitionCode")
                            or item.get("workflowDefinitionCode")
                            or item.get("definitionCode")
                        ) == str(workflow_code)
                    ),
                    None,
                )
                pages.append(
                    {
                        "page_no": page_no,
                        "endpoint": endpoint,
                        "success": success,
                        "msg": msg,
                        "visible_count": len(total_list),
                        "matched_by_id": bool(match_by_id),
                        "matched_by_workflow": bool(match_by_workflow),
                        "first_ids": [item.get("id") for item in total_list[:5]],
                    }
                )
                if match_by_id or match_by_workflow:
                    found = match_by_id or match_by_workflow
                    break

                total_pages = data.get("totalPage") if isinstance(data, dict) else None
                if not success or not total_pages or page_no >= total_pages:
                    break

            probes.append(
                {
                    "style": style,
                    "state_type": state_type or "NONE",
                    "pages": pages,
                    "matched_instance": {
                        "id": found.get("id"),
                        "state": found.get("state"),
                        "startTime": found.get("startTime"),
                        "processDefinitionCode": found.get("processDefinitionCode")
                        or found.get("workflowDefinitionCode")
                        or found.get("definitionCode"),
                    } if found else None,
                }
            )

    recent_match = repair.find_recent_instance_by_workflow(
        project_code,
        workflow_code,
        launched_at=launched_at,
    )
    return {
        "project_code": project_code,
        "instance_id": instance_id,
        "workflow_code": workflow_code,
        "launched_at": launched_at,
        "recent_match": recent_match,
        "list_probes": probes,
    }


def probe_fuyan_instance(instance_id, workflow_code, launched_at=None, project_code=None):
    launched_at = launched_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    project_code = project_code or DS_CONFIG["fuyan_project_code"]

    detail = repair.collect_instance_query_diagnostics(
        project_code=project_code,
        instance_id=instance_id,
        workflow_code=workflow_code,
        launched_at=launched_at,
    )
    paged_lists = probe_list_pages(
        project_code=project_code,
        instance_id=instance_id,
        workflow_code=workflow_code,
        launched_at=launched_at,
    )
    return {
        "ds_base": DS_CONFIG["base_url"],
        "default_fuyan_project_code": DS_CONFIG["fuyan_project_code"],
        "configured_fuyan_workflows": get_fuyan_candidates(),
        "probe_target": {
            "project_code": project_code,
            "workflow_code": workflow_code,
            "instance_id": instance_id,
            "launched_at": launched_at,
        },
        "detail_probe": detail,
        "paged_list_probe": paged_lists,
    }


def main():
    parser = argparse.ArgumentParser(description="Probe fuyan instance visibility")
    parser.add_argument("--instance-id", required=True, help="Start response id or expected instance id")
    parser.add_argument("--workflow-code", required=True, help="Fuyan workflow code")
    parser.add_argument("--project-code", help="Override project code for this probe")
    parser.add_argument("--launched-at", help="Workflow launch time, e.g. 2026-05-11 09:35:44")
    args = parser.parse_args()

    report = probe_fuyan_instance(
        instance_id=args.instance_id,
        workflow_code=args.workflow_code,
        project_code=args.project_code,
        launched_at=args.launched_at,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
