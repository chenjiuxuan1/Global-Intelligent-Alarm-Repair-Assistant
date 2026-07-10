# Multi-Country Runtime Config Design

**Context**

The current repository mixes runtime configuration with business logic. Main-path scripts hardcode DolphinScheduler base URLs, tokens, project codes, workflow codes, tenant/environment identifiers, table names, webhook endpoints, TV bot settings, and absolute workspace paths. This blocks migration to Indonesia and makes future country rollouts error-prone.

**Goal**

Centralize main-path runtime configuration behind one shared module so country migrations can be completed by updating environment variables and documented config values, without editing Python business logic.

**Scope**

This first round only refactors the main path:

- `config/config.py`
- `core/repair_strict_7step.py`
- `core/auto_stop_abnormal_schedule.py`
- `dolphinscheduler/run_fuyan_workflows.py`
- `alert/db_config.py`
- `alert/alert_bridge.py`
- `alert/send_alert.py`
- `core/send_tv_report.py`

Auxiliary DolphinScheduler scripts will be handled in a second round.

**Approach**

Use one shared configuration layer in `config/config.py` and keep per-script changes narrow:

1. Add a common runtime config surface for:
   - workspace paths
   - DolphinScheduler connection and execution parameters
   - primary project codes
   - recheck workflow definitions
   - database connection
   - OpenClaw webhook
   - TV bot config
   - alert/result table names
2. Keep environment variable loading in `config/auto_load_env.py`, but expand it so new variables can also be hydrated from `~/.bashrc`.
3. Replace hardcoded constants in main-path scripts with reads from the shared config module.
4. Replace hardcoded `/home/node/.openclaw/workspace` imports/paths with dynamically resolved repository root defaults, while still allowing override through environment variables.
5. Document every country-facing variable in:
   - `.env.example`
   - a migration guide for Indonesia and future countries

**Configuration Model**

The shared module should expose plain dictionaries and helpers so the current scripts can adopt it with minimal churn:

- `WORKSPACE_CONFIG`
- `DS_CONFIG`
- `TV_CONFIG`
- `DB_CONFIG`
- `OPENCLAW_CONFIG`
- `TABLE_CONFIG`
- `FUYAN_WORKFLOWS`
- validation helpers for required secrets like `DS_TOKEN` and `DB_PASSWORD`

`FUYAN_WORKFLOWS` will be configurable through a JSON environment variable so country-specific workflow lists can be replaced without code changes. The repo can still ship domestic defaults as a fallback for local continuity until Indonesia values are provided.

**Error Handling**

- Missing secret-like values should fail loudly with actionable messages.
- Non-secret defaults may remain for backward compatibility where safe, but should be documented as domestic defaults.
- Invalid JSON in workflow configuration should raise a clear configuration error.

**Testing**

Add focused unit tests that prove:

- shared config reads environment overrides correctly
- recheck workflow JSON is parsed from environment
- scripts use shared config values instead of old hardcoded values

The tests should avoid external network or database access.

**Documentation**

Add a migration guide that records:

- every required variable name
- whether it is required or optional
- what it controls
- what Indonesia needs to provide
- how other countries can clone the same pattern

**Non-Goals**

- Refactoring all auxiliary DS analysis/debug scripts in this round
- Introducing a country selector framework or multiple config files per country
- Changing business logic for repair, alert forwarding, or TV formatting beyond config plumbing
