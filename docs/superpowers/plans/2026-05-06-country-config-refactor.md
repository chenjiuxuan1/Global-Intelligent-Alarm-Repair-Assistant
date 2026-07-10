# Country Config Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize main-path runtime configuration so Indonesia and future country migrations can be completed through environment variables and documented values instead of code edits.

**Architecture:** Expand `config/config.py` into the single shared runtime configuration surface, keep `config/auto_load_env.py` as the environment hydrator, and refactor main-path scripts to consume shared config dictionaries plus helper functions. Preserve current behavior with domestic defaults where safe, but remove hardcoded secrets and path assumptions from the main path.

**Tech Stack:** Python 3, `unittest`, environment variables, JSON-based workflow config

---

### Task 1: Add failing tests for shared runtime configuration

**Files:**
- Create: `tests/country_config_checks.py`

- [ ] **Step 1: Write the failing test**

```python
def test_get_fuyan_workflows_reads_json_from_environment():
    os.environ["FUYAN_WORKFLOWS_JSON"] = json.dumps([{"name": "ID", "code": "1", "level": "all"}])
    module = load_module()
    assert module.FUYAN_WORKFLOWS[0]["name"] == "ID"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.country_config_checks -v`
Expected: FAIL because shared config helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add shared config helpers and workflow parsing to `config/config.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.country_config_checks -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/country_config_checks.py config/config.py
git commit -m "test: cover shared country config loading"
```

### Task 2: Refactor shared config and env loading

**Files:**
- Modify: `config/config.py`
- Modify: `config/auto_load_env.py`
- Modify: `config/README.md`

- [ ] **Step 1: Write the failing test**

Extend config tests to assert new env vars are loaded and parsed consistently.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.country_config_checks -v`
Expected: FAIL on missing keys or parsing behavior.

- [ ] **Step 3: Write minimal implementation**

Add shared config dictionaries, helper functions, dynamic repo root defaults, and broader env hydration.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.country_config_checks -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/config.py config/auto_load_env.py config/README.md tests/country_config_checks.py
git commit -m "feat: centralize shared runtime config"
```

### Task 3: Refactor the repair main path to consume shared config

**Files:**
- Modify: `core/repair_strict_7step.py`
- Test: `tests/repair_strict_7step_checks.py`

- [ ] **Step 1: Write the failing test**

Add assertions that module constants come from shared config and that workspace paths are dynamic.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.repair_strict_7step_checks -v`
Expected: FAIL because constants are still hardcoded.

- [ ] **Step 3: Write minimal implementation**

Replace hardcoded DS, workflow, path, tenant, environment, and table-name values with shared config reads.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.repair_strict_7step_checks -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/repair_strict_7step.py tests/repair_strict_7step_checks.py
git commit -m "feat: move repair flow to shared runtime config"
```

### Task 4: Refactor alerting and TV scripts to consume shared config

**Files:**
- Modify: `alert/db_config.py`
- Modify: `alert/alert_bridge.py`
- Modify: `alert/send_alert.py`
- Modify: `core/send_tv_report.py`
- Modify: `core/auto_stop_abnormal_schedule.py`
- Modify: `dolphinscheduler/run_fuyan_workflows.py`
- Test: `tests/send_tv_report_checks.py`

- [ ] **Step 1: Write the failing test**

Add assertions for TV config and any other script-level config reads that remain hardcoded.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.send_tv_report_checks -v`
Expected: FAIL because scripts still use local constants.

- [ ] **Step 3: Write minimal implementation**

Replace local hardcoded constants with shared config dictionaries and dynamic workspace paths.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.send_tv_report_checks -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add alert/db_config.py alert/alert_bridge.py alert/send_alert.py core/send_tv_report.py core/auto_stop_abnormal_schedule.py dolphinscheduler/run_fuyan_workflows.py tests/send_tv_report_checks.py
git commit -m "feat: move alert and TV scripts to shared runtime config"
```

### Task 5: Add environment template and migration documentation

**Files:**
- Create: `.env.example`
- Create: `docs/country-config-migration.md`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

No automated test required; treat documentation as configuration deliverable.

- [ ] **Step 2: Run test to verify it fails**

Skip. This task is documentation-only.

- [ ] **Step 3: Write minimal implementation**

Document all country-facing variables, migration steps, and Indonesia input checklist.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.country_config_checks tests.repair_strict_7step_checks tests.send_tv_report_checks -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .env.example docs/country-config-migration.md README.md
git commit -m "docs: add country config migration guide"
```
