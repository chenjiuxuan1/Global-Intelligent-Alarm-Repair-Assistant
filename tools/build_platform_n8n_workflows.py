#!/usr/bin/env python3
"""Build sanitized n8n workflow templates for the unified platform.

The source workflow exports may contain inline secrets. This script keeps the
node topology, webhook paths, and credential references, but replaces execution
commands with platform commands that read secrets from the remote environment.
"""

import copy
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "deploy" / "n8n" / "templates"
PLATFORM_REPO = "/root/Global-Intelligent-Alarm-Repair-Assistant"


COUNTRIES = {
    "cn": {
        "source": "/Users/jiangchuanchen/Downloads/智能告警修复-中国.json",
        "display": "中国",
        "ssh": "ssh -p 36000 root@10.20.47.14",
        "legacy_repo": "/root/CN-Intelligent-Alarm-Repair-Assistant",
        "pull": (
            "GIT_SSH_COMMAND='ssh -i /root/.ssh/cn_repo_deploy_key -o IdentitiesOnly=yes' "
            "git pull origin master"
        ),
        "runtime_env": {
            "APP_COUNTRY": "cn",
            "APP_WORKSPACE": PLATFORM_REPO,
            "DS_BASE_URL": "http://10.20.47.14:12345/dolphinscheduler",
            "DS_API_GET_TIMEOUT_SECONDS": "30",
            "DS_API_GET_RETRY_COUNT": "2",
            "DS_WORKFLOW_LIST_PAGE_SIZE": "20",
            "DB_HOST": "rm-uf60amp9vz996n520.mysql.rds.aliyuncs.com",
            "DB_PORT": "3306",
            "DB_USER": "e_ds",
            "DB_NAME": "wattrel",
            "TV_MENTIONS": "owenzhang@kn.group,rockyzong@kn.group",
        },
    },
    "th": {
        "source": "/Users/jiangchuanchen/Downloads/智能告警修复-泰国.json",
        "display": "泰国",
        "ssh": "ssh -p 36000 root@192.168.20.236",
        "legacy_repo": "/root/TH-Intelligent-Alarm-Repair-Assistant",
        "pull": "git pull origin master",
        "runtime_env": {
            "APP_COUNTRY": "th",
            "APP_WORKSPACE": PLATFORM_REPO,
            "DS_API_GET_TIMEOUT_SECONDS": "3",
            "DS_API_RETRY_COUNT": "1",
            "DS_STEP2_PROGRESS_EVERY": "5",
        },
    },
    "ine": {
        "source": "/Users/jiangchuanchen/Downloads/智能告警修复-印尼.json",
        "display": "印尼",
        "ssh": "ssh -p 36000 root@192.168.21.236",
        "legacy_repo": "/root/INE-Intelligent-Alarm-Repair-Assistant",
        "pull": "git fetch origin && git reset --hard origin/master",
        "runtime_env": {
            "APP_COUNTRY": "ine",
            "APP_WORKSPACE": PLATFORM_REPO,
            "TV_MENTIONS": "gretchenhe@kn.group,riverzhai@kn.group",
        },
    },
    "pk": {
        "source": "/Users/jiangchuanchen/Downloads/智能告警修复-巴基斯坦.json",
        "display": "巴基斯坦",
        "ssh": "ssh root@10.20.84.176",
        "legacy_repo": "/root/PK-Intelligent-Alarm-Repair-Assistant",
        "pull": "git checkout master && git pull origin master",
        "runtime_env": {
            "APP_COUNTRY": "pk",
            "APP_WORKSPACE": PLATFORM_REPO,
        },
    },
    "mx": {
        "source": "/Users/jiangchuanchen/Downloads/智能告警修复-墨西哥.json",
        "display": "墨西哥",
        "ssh": "ssh -p 36000 root@172.20.220.165",
        "legacy_repo": "/root/MX-Intelligent-Alarm-Repair-Assistant",
        "pull": "git fetch origin && git reset --hard origin/master",
        "runtime_env": {
            "APP_COUNTRY": "mx",
            "APP_WORKSPACE": PLATFORM_REPO,
            "DS_ENVIRONMENT_CODE": "12813621425120",
            "DS_TENANT_CODE": "dolphinscheduler",
            "TV_API_URL": "https://tv-service-alert.kuainiu.chat/alert/v2/array",
            "TV_BOT_ID": "163ad872-4b4d-4493-8ec7-838f8eb9848d",
            "TV_MENTIONS": "kuiwu@kn.group,enzodeng@kn.group",
        },
    },
    "ph": {
        "source": "/Users/jiangchuanchen/Downloads/智能告警修复-菲律宾.json",
        "display": "菲律宾",
        "ssh": "ssh root@10.20.10.12",
        "legacy_repo": "/root/PH-Intelligent-Alarm-Repair-Assistant",
        "pull": "git fetch origin && git reset --hard origin/master",
        "runtime_env": {
            "APP_COUNTRY": "ph",
            "APP_WORKSPACE": PLATFORM_REPO,
            "TV_API_URL": "https://tv-service-alert.kuainiu.chat/alert/v2/array",
            "TV_MENTIONS": "simontang@kn.group,jiangchuanchen@kn.group",
        },
    },
}


SECRET_PATTERNS = [
    re.compile(r'(DS_TOKEN=)["\']?[^"\'\s]+["\']?'),
    re.compile(r'(DB_PASSWORD=)["\']?[^"\'\s]+["\']?'),
    re.compile(r'(--sr-password\s+)["\'][^"\']+["\']'),
    re.compile(r'(--sr-backup-password\s+)["\'][^"\']+["\']'),
    re.compile(r'("token:\s*)[^"]+(")'),
]


def shell_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def env_prefix(runtime_env):
    parts = [f"{key}={shell_quote(value)}" for key, value in runtime_env.items()]
    return " ".join(parts)


def runtime_env_for_country(country):
    runtime_env = dict(COUNTRIES[country]["runtime_env"])
    runtime_env.setdefault("WORKFLOW_CODE_ROOT", "/data/git/starrocks/workflow")
    runtime_env.setdefault("WORKFLOW_CODE_COUNTRY", country)
    return runtime_env


def source_env_prefix(country):
    return (
        "set -a && [ -f .env.local ] && source .env.local; set +a && "
        f"{env_prefix(runtime_env_for_country(country))}"
    )


def remote(country, inner_command):
    cfg = COUNTRIES[country]
    return f"{cfg['ssh']} {shell_quote(inner_command)}"


def platform_command(country, body):
    return f"cd {PLATFORM_REPO} && {source_env_prefix(country)} {body}"


def pull_command(country):
    cfg = COUNTRIES[country]
    return remote(country, f"cd {PLATFORM_REPO} && {cfg['pull']}")


def check_command(country):
    return remote(country, platform_command(country, "python3 tools/task_execution_checker.py --task repair"))


def repair_command(country, unbuffered=False):
    python = "python3 -u" if unbuffered else "python3"
    return remote(country, platform_command(country, f"{python} core/repair_strict_7step.py"))


def cn_external_command(command):
    command = command.replace("/root/CN-Intelligent-Alarm-Repair-Assistant", PLATFORM_REPO)
    command = re.sub(r"--sr-password\s+'[^']+'", "--sr-password '${SR_PASSWORD}'", command)
    command = re.sub(r"--sr-backup-password\s+'[^']+'", "--sr-backup-password '${SR_BACKUP_PASSWORD}'", command)
    return command


def diagnostic_command(country, original):
    if country == "cn":
        return cn_external_command(original)
    if "probe_ds_api_mode.py" in original:
        return remote(country, platform_command(country, "python3 tools/probe_ds_api_mode.py --instance-id ${DS_PROBE_INSTANCE_ID}"))
    if "workflow-instances" in original or "find /data" in original:
        return re.sub(r'(?i)token:\s*[0-9a-f]+', "token: ${DS_TOKEN}", original)
    return original


def replace_command(country, node_name, original_command):
    if node_name in {"拉取最新代码"}:
        return pull_command(country)
    if node_name in {"环境检测", "执行环境检测"}:
        return check_command(country)
    if node_name == "智能修复":
        return repair_command(country, unbuffered=False)
    if node_name == "智能修复1":
        return repair_command(country, unbuffered=(country == "th"))
    return diagnostic_command(country, original_command)


def redact_command(command):
    redacted = command
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(1) + "${SECRET}" + (match.group(2) if len(match.groups()) > 1 else ""), redacted)
    return redacted


def build_template(country):
    source_path = Path(COUNTRIES[country]["source"])
    fallback_path = OUTPUT_DIR / f"智能告警修复-{COUNTRIES[country]['display']}-统一平台模板.json"
    if not source_path.exists() and fallback_path.exists():
        source_path = fallback_path
    workflow = json.loads(source_path.read_text(encoding="utf-8"))
    result = copy.deepcopy(workflow)
    source_workflow_name = workflow.get("meta", {}).get("sourceWorkflowName") or workflow["name"]
    result["name"] = f"{source_workflow_name}-统一平台模板"
    result["active"] = False
    result.setdefault("meta", {})["platformTemplate"] = True
    result["meta"]["sourceWorkflowName"] = source_workflow_name
    result["meta"]["platformCountry"] = country
    result["meta"]["platformRepo"] = PLATFORM_REPO

    for node in result.get("nodes", []):
        parameters = node.get("parameters", {})
        if "command" not in parameters:
            continue
        command = parameters["command"]
        if command.startswith("="):
            command = command[1:]
            prefix = "="
        else:
            prefix = ""
        parameters["command"] = prefix + redact_command(
            replace_command(country, node.get("name", ""), command)
        )

    return result


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for country in COUNTRIES:
        template = build_template(country)
        output_path = OUTPUT_DIR / f"智能告警修复-{COUNTRIES[country]['display']}-统一平台模板.json"
        output_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(output_path)


if __name__ == "__main__":
    main()
