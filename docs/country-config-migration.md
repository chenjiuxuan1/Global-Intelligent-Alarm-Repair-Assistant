# Multi-Country Config Migration Guide

## Purpose

This repository now uses a shared runtime configuration layer for the main path. To migrate a country environment, update environment variables instead of editing Python code.

First-round main-path coverage:

- `config/config.py`
- `core/repair_strict_7step.py`
- `core/auto_stop_abnormal_schedule.py`
- `dolphinscheduler/run_fuyan_workflows.py`
- `alert/db_config.py`
- `alert/alert_bridge.py`
- `alert/send_alert.py`
- `core/send_tv_report.py`

Auxiliary DolphinScheduler scripts are not included yet and should be handled in the second round.

## How Config Works

All main-path scripts now read from `config/config.py`.

`config/auto_load_env.py` will also try to load supported variables from `~/.bashrc` if they are not already present in the process environment.

Recommended deployment pattern:

1. Copy `.env.example` or the variable list below.
2. Fill in country-specific values.
3. Export them in the runtime shell or write them into `~/.bashrc`.
4. Run the target script without editing code.

## Variable Reference

### Workspace

`APP_WORKSPACE`
- Required: recommended
- Purpose: runtime workspace root used for record files and derived paths
- Example: `/home/node/.openclaw/workspace` or repo deploy path on the target machine

`SCHEDULE_EXPORT_CSV`
- Required: optional
- Purpose: CSV source for abnormal schedule detection
- Default: `<APP_WORKSPACE>/dolphinscheduler/schedules_export.csv`

### DolphinScheduler

`DS_BASE_URL`
- Required: yes
- Purpose: DolphinScheduler base URL
- Example: `http://your-ds-host:12345/dolphinscheduler`

`DS_TOKEN`
- Required: yes
- Purpose: DolphinScheduler API token

`DS_PROJECT_CODE`
- Required: yes
- Purpose: main project code used by repair and schedule checks

`DS_FUYAN_PROJECT_CODE`
- Required: yes
- Purpose: recheck project code

`DS_FUYAN_PROJECT_NAME`
- Required: optional
- Purpose: display name for recheck project in helper scripts

`DS_ENVIRONMENT_CODE`
- Required: yes
- Purpose: DS execution environment code used when starting workflows

`DS_TENANT_CODE`
- Required: yes
- Purpose: DS tenant code used when starting workflows

### Recheck workflows

`FUYAN_WORKFLOWS_JSON`
- Required: yes for non-domestic rollout
- Purpose: full recheck workflow list for the target country
- Format: JSON array

Each item should include:

- `project_name`
- `project_code`
- `workflow_name`
- `workflow_code`
- `schedule`
- `level`

The main repair script also accepts the shorter fields `name` and `code`, but keeping both sets is recommended for readability and compatibility.

### Database

`DB_HOST`
- Required: yes
- Purpose: MySQL host for quality tables

`DB_PORT`
- Required: yes
- Purpose: MySQL port

`DB_USER`
- Required: yes
- Purpose: MySQL username

`DB_PASSWORD`
- Required: yes
- Purpose: MySQL password

`DB_NAME`
- Required: yes
- Purpose: MySQL database name

### Table names

`QUALITY_RESULT_TABLE`
- Required: optional
- Purpose: result table used by repair flow
- Default: `wattrel_quality_result`

`QUALITY_ALERT_TABLE`
- Required: optional
- Purpose: alert table used by alert bridge and alert sender
- Default: `wattrel_quality_alert`

### OpenClaw webhook

`OPENCLAW_WEBHOOK`
- Required: depends on deployment
- Purpose: wake endpoint for alert forwarding

`OPENCLAW_HOOK_TOKEN`
- Required: depends on deployment
- Purpose: bearer token for the webhook

### TV bot

`TV_API_URL`
- Required: depends on deployment
- Purpose: TV robot API endpoint

`TV_BOT_ID`
- Required: depends on deployment
- Purpose: TV bot identifier

`TV_APP_ID`
- Required: optional
- Purpose: TV app id
- Default: `alert`

`TV_MENTIONS`
- Required: optional
- Purpose: comma-separated mention list for repair report delivery

## Indonesia Migration Checklist

Please prepare these values for the Indonesia environment:

1. `DS_BASE_URL`
2. `DS_TOKEN`
3. `DS_PROJECT_CODE`
4. `DS_FUYAN_PROJECT_CODE`
5. `DS_ENVIRONMENT_CODE`
6. `DS_TENANT_CODE`
7. `FUYAN_WORKFLOWS_JSON`
8. `DB_HOST`
9. `DB_PORT`
10. `DB_USER`
11. `DB_PASSWORD`
12. `DB_NAME`
13. `QUALITY_RESULT_TABLE` if different from default
14. `QUALITY_ALERT_TABLE` if different from default
15. `OPENCLAW_WEBHOOK` if Indonesia uses a different OpenClaw service
16. `OPENCLAW_HOOK_TOKEN` if different
17. `TV_API_URL` if Indonesia uses a different alert API
18. `TV_BOT_ID` if Indonesia uses a different robot
19. `APP_WORKSPACE` if the deploy path is not the repository root
20. `SCHEDULE_EXPORT_CSV` if the abnormal schedule CSV lives elsewhere

## Suggested Country Rollout Process

1. Copy `.env.example` into the deployment environment.
2. Fill in that country's DS, DB, workflow, OpenClaw, and TV values.
3. Export variables or add them to `~/.bashrc`.
4. Run:
   - `python3 -m unittest tests.country_config_checks tests.repair_strict_7step_checks tests.send_tv_report_checks -v`
5. Smoke-test:
   - `python3 core/send_tv_report.py --test`
   - `python3 dolphinscheduler/run_fuyan_workflows.py --help`
   - main repair flow in a controlled environment

## Runtime Notes From 2026-05-10

Two production behaviors were confirmed during the Indonesia rollout:

1. DolphinScheduler may return a successful `start-process-instance` response before the new instance is visible from the detail API.
   - The repair flow now keeps polling and falls back to the running-instance list before treating this as a real failure.
   - If a report mentions query failure, first distinguish between "instance not yet visible" and a true API/config issue.

2. Manual repair reruns must avoid overlapping with scheduled workflow execution.
   - The repair flow now checks for existing running instances of the same workflow before starting a rerun.
   - If a scheduled or manual instance is already running, the task is skipped with a clear conflict reason instead of forcing another start.
   - When rolling out to another country, confirm the repair cron is staggered away from large scheduled workflow windows.

## Remaining Second-Round Work

These scripts still need to be migrated in round two:

- `dolphinscheduler/check_running.py`
- `dolphinscheduler/search_table.py`
- `dolphinscheduler/check_orphan_schedule.py`
- `dolphinscheduler/analyze_startup.py`
- any other helper script still hardcoding domestic DS settings
