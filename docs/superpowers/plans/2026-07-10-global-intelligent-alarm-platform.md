# Global Intelligent Alarm Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new unified platform repository that runs the existing intelligent alarm repair workflows for CN, TH, INE, PK, MX, and PH from one codebase.

**Architecture:** Keep the current Python project shape, copy the existing main-path implementation into a new platform repository, and move country differences into `config/country_profiles/*.env.example`. `config/config.py` loads `.env.local` first and then an optional country profile selected by `COUNTRY` or `APP_COUNTRY`, while real secrets stay in local environment files.

**Tech Stack:** Python 3, standard library configuration loading, existing DolphinScheduler/MySQL/TV alert scripts, `unittest`.

---

### Task 1: Scaffold Platform Repository

**Files:**
- Create: `/Users/jiangchuanchen/Desktop/codex使用/Global-Intelligent-Alarm-Repair-Assistant`
- Source baseline: `/Users/jiangchuanchen/Desktop/PH-Intelligent-Alarm-Repair-Assistant`

- [x] **Step 1: Create the repository directory and copy the existing project shape**

Copy main directories and files from the PH repository because it already has the shared migration guide, `.env.example`, and the same runtime structure as the other countries.

- [x] **Step 2: Remove source repository metadata from the platform copy**

Do not copy `.git`, local Playwright traces, or local `.env.local` secrets.

### Task 2: Add Country Profile Loading

**Files:**
- Modify: `/Users/jiangchuanchen/Desktop/codex使用/Global-Intelligent-Alarm-Repair-Assistant/config/config.py`
- Create: `/Users/jiangchuanchen/Desktop/codex使用/Global-Intelligent-Alarm-Repair-Assistant/tests/country_profile_loader_checks.py`

- [ ] **Step 1: Add a profile loader test**

Test that `APP_COUNTRY=th` loads `config/country_profiles/th.env.example` when the local env file does not define the same keys.

- [ ] **Step 2: Implement profile resolution**

Support `COUNTRY` and `APP_COUNTRY`, normalize values to lowercase, allow `APP_COUNTRY_PROFILE` to point at a custom profile file, and keep process environment values highest priority.

- [ ] **Step 3: Run the profile loader test**

Run: `python3 -m unittest tests.country_profile_loader_checks -v`

### Task 3: Add Six Country Profile Examples

**Files:**
- Create: `config/country_profiles/cn.env.example`
- Create: `config/country_profiles/th.env.example`
- Create: `config/country_profiles/ine.env.example`
- Create: `config/country_profiles/pk.env.example`
- Create: `config/country_profiles/mx.env.example`
- Create: `config/country_profiles/ph.env.example`

- [ ] **Step 1: Create example profiles**

Use non-secret values from each current repository where safe. Use `replace_with_*` placeholders for tokens and passwords.

- [ ] **Step 2: Keep country-specific operational differences in profiles**

Include DS API mode, start endpoint, DB host/port/user, table names, OpenClaw settings, TV settings, and blocked workflow settings.

### Task 4: Document the Platform Entry Point

**Files:**
- Modify: `/Users/jiangchuanchen/Desktop/codex使用/Global-Intelligent-Alarm-Repair-Assistant/README.md`
- Create: `/Users/jiangchuanchen/Desktop/codex使用/Global-Intelligent-Alarm-Repair-Assistant/docs/platform-migration.md`

- [ ] **Step 1: Update README**

Document that the platform replaces six code copies with one codebase and country profiles.

- [ ] **Step 2: Add migration notes**

Document the phased migration: old repositories remain rollback baselines, main-path scripts migrate first, auxiliary DS helper scripts migrate second.

### Task 5: Verify Main Path

**Files:**
- Test: `/Users/jiangchuanchen/Desktop/codex使用/Global-Intelligent-Alarm-Repair-Assistant/tests/*.py`

- [ ] **Step 1: Run configuration tests**

Run: `python3 tests/country_config_checks.py`

- [ ] **Step 2: Run focused unit tests**

Run: `python3 -m unittest tests.country_profile_loader_checks tests.repair_strict_7step_checks tests.send_tv_report_checks -v`

- [ ] **Step 3: Initialize git repository**

Run `git init`, add the platform files, and create the first local commit after tests pass.
