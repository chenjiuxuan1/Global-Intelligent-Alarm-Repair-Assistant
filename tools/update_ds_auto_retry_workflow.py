#!/usr/bin/env python3
"""Update exported n8n DS auto-retry workflows to the continuous-retry policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPLACEMENTS = {
    "export DS_FAILED_MAX_RETRIES=3": "export DS_FAILED_MAX_RETRIES=0",
    "export DS_FAILED_INSTANCE_TIMEOUT_SECONDS=1800": "export DS_FAILED_INSTANCE_TIMEOUT_SECONDS=0",
    "export DS_FAILED_MONITOR_INTERVAL_SECONDS=60": "export DS_FAILED_MONITOR_INTERVAL_SECONDS=10",
    "export DS_FAILED_COUNTRY_ACTIVE_LIMIT=10": (
        "export DS_FAILED_RETRY_DELAY_SECONDS=10',\n    "
        "'export DS_FAILED_COUNTRY_ACTIVE_LIMIT=10"
    ),
    "最多 3 次，从失败节点开始执行，单实例最多监控 30 分钟": (
        "先解析任务日志；SQL 错误不重跑，可恢复错误立即持续重跑直至成功"
    ),
}


def update(path: Path) -> None:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for node in workflow.get("nodes", []):
        params = node.get("parameters", {})
        code = params.get("jsCode")
        if not isinstance(code, str):
            continue
        updated = code
        for old, new in REPLACEMENTS.items():
            updated = updated.replace(old, new)
        if updated != code:
            params["jsCode"] = updated
            changed = True
    if not changed:
        raise SystemExit(f"no matching retry policy found in {path}")
    path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        update(Path(argument))
