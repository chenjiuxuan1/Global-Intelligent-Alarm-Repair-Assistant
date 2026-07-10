# Platform Migration

## Goal

Replace the six country-specific code copies with one platform repository:

- `CN-Intelligent-Alarm-Repair-Assistant`
- `TH-Intelligent-Alarm-Repair-Assistant`
- `INE-Intelligent-Alarm-Repair-Assistant`
- `PK-Intelligent-Alarm-Repair-Assistant`
- `MX-Intelligent-Alarm-Repair-Assistant`
- `PH-Intelligent-Alarm-Repair-Assistant`

The old repositories remain rollback baselines until each country has passed smoke tests on this platform.

## Phase 1 Scope

Phase 1 keeps the existing Python project structure and adds country profile loading.

Covered main-path scripts:

- `config/config.py`
- `core/repair_strict_7step.py`
- `core/auto_stop_abnormal_schedule.py`
- `core/send_tv_report.py`
- `alert/db_config.py`
- `alert/alert_bridge.py`
- `alert/send_alert.py`
- `dolphinscheduler/run_fuyan_workflows.py`

Country differences live in:

- `config/country_profiles/cn.env.example`
- `config/country_profiles/th.env.example`
- `config/country_profiles/ine.env.example`
- `config/country_profiles/pk.env.example`
- `config/country_profiles/mx.env.example`
- `config/country_profiles/ph.env.example`

## Runtime Selection

Use either `APP_COUNTRY` or `COUNTRY`:

```bash
APP_COUNTRY=ph python3 core/repair_strict_7step.py
COUNTRY=th python3 core/send_tv_report.py --test
```

Use `APP_COUNTRY_PROFILE` when a deployment needs a profile outside the repository:

```bash
APP_COUNTRY_PROFILE=/etc/alarm-repair/th.env python3 core/repair_strict_7step.py
```

Configuration precedence:

1. Process environment variables
2. `.env.local` or `APP_ENV_FILE`
3. Selected country profile
4. Code defaults

## Phase 2 Scope

The following auxiliary DS scripts should be reviewed next because older country repositories note that they may still assume domestic DS settings:

- `dolphinscheduler/check_running.py`
- `dolphinscheduler/search_table.py`
- `dolphinscheduler/check_orphan_schedule.py`
- `dolphinscheduler/analyze_startup.py`
- any tool script that opens DS URLs or project codes without reading `config/config.py`

## Country Rollout Checklist

For each country:

1. Copy `config/country_profiles/<country>.env.example` to `.env.local` or the deployment secret store.
2. Fill real DS, DB, OpenClaw, TV, and workflow values.
3. Run `APP_COUNTRY=<country> python3 tests/country_config_checks.py`.
4. Run `APP_COUNTRY=<country> python3 -m unittest tests.repair_strict_7step_checks tests.send_tv_report_checks -v`.
5. Run `APP_COUNTRY=<country> python3 core/send_tv_report.py --test`.
6. Run the repair flow in a controlled window.
7. Compare output with the old country repository before switching cron or DS triggers.
