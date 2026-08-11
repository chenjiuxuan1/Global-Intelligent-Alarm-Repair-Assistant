# DS Auto-Retry Monitor Circuit Breaker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound each DS failed-instance auto-retry lifecycle to 30 minutes and add a per-country circuit breaker that stops all monitoring when 10 active failed instances are reached.

**Architecture:** Add a focused `CountryMonitorRegistry` module backed by a country-local JSON file and `flock`. Integrate its decisions into the existing background runner, then replace count-based 24-hour monitoring with a 30-minute monotonic deadline and explicit success, three-failure, timeout, and country-unhealthy terminal paths.

**Tech Stack:** Python 3.9+, standard library (`fcntl`, `json`, `os`, `time`, `pathlib`, `unittest`).

---

## File map

- Create `tools/ds_retry_monitor_registry.py`: atomic per-country active-monitor registry, stale cleanup, circuit opening, extension, and recovery.
- Create `tests/ds_retry_monitor_registry_checks.py`: isolated registry state-machine tests with injected clock and PID liveness.
- Modify `tools/ds_failed_auto_retry.py`: lifecycle deadline, registry guard integration, notification builders, and main-process registration.
- Modify `tests/ine_ds_failed_auto_retry_checks.py`: end-to-end retry lifecycle and notification regression tests.

### Task 1: Implement the per-country monitor registry

**Files:**
- Create: `tools/ds_retry_monitor_registry.py`
- Create: `tests/ds_retry_monitor_registry_checks.py`

- [ ] **Step 1: Write failing registry tests**

```python
class CountryMonitorRegistryTests(unittest.TestCase):
    def test_tenth_registration_opens_circuit_once(self):
        clock = FakeClock(1_000.0)
        registry = CountryMonitorRegistry(path, active_limit=10, circuit_seconds=1800,
                                          stale_seconds=300, clock=clock,
                                          process_alive=lambda _: True)
        for index in range(9):
            self.assertTrue(registry.register(f"pk:p:{index}", pid=100 + index)["accepted"])
        tenth = registry.register("pk:p:9", pid=109)
        self.assertFalse(tenth["accepted"])
        self.assertTrue(tenth["circuit_open"])
        self.assertTrue(tenth["alert_required"])
        repeated = registry.heartbeat("pk:p:0", pid=100)
        self.assertTrue(repeated["circuit_open"])
        self.assertFalse(repeated["alert_required"])

    def test_circuit_reopens_after_cooldown_when_below_limit(self):
        # Open at 10, unregister all, advance 1800 seconds, register one new monitor.
        self.assertTrue(registry.register("pk:new", pid=999)["accepted"])

    def test_dead_pid_and_stale_heartbeat_are_removed(self):
        self.assertEqual(registry.snapshot()["active_count"], 0)
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
PYTHONPATH=. python3 -m unittest -v tests.ds_retry_monitor_registry_checks
```

Expected: import failure because `tools.ds_retry_monitor_registry` does not exist.

- [ ] **Step 3: Implement the registry**

Implement `CountryMonitorRegistry` with constructor arguments `path`, `active_limit=10`,
`circuit_seconds=1800`, `stale_seconds=300`, injectable `clock=time.time`, and injectable
`process_alive`. Its public methods are `register(retry_key, pid, request_id, instance_id)`,
`heartbeat(retry_key, pid)`, `unregister(retry_key, pid)`, and `snapshot()`.

Every mutation uses an adjacent lock file and `fcntl.flock(LOCK_EX)`. Under the lock: load state, back up corrupt JSON, clean dead/stale PIDs, refresh expired circuit state, mutate, atomically write JSON, and unlock. Decisions always include `accepted`, `circuit_open`, `alert_required`, `active_count`, and `circuit_open_until`. Only the 9-to-10 transition returns `alert_required=True`.

- [ ] **Step 4: Run registry tests and verify GREEN**

Run the Step 2 command. Expected: all registry tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add tools/ds_retry_monitor_registry.py tests/ds_retry_monitor_registry_checks.py
git commit -m "feat: add country DS monitor registry"
```

### Task 2: Integrate registration and circuit decisions

**Files:**
- Modify: `tools/ds_failed_auto_retry.py`
- Modify: `tests/ine_ds_failed_auto_retry_checks.py`

- [ ] **Step 1: Write failing integration tests**

```python
def test_country_circuit_blocks_new_retry_without_gateway_calls(self):
    # register returns circuit_open; result is country_circuit_open; no gateway call.

def test_country_circuit_alert_is_sent_once(self):
    # alert_required=True sends country, count 10, 30-minute circuit, manual action.

def test_existing_monitor_stops_when_heartbeat_sees_circuit(self):
    # Guard opens during polling; no later DS call and no instance final alert.
```

- [ ] **Step 2: Run integration tests and verify RED**

Expected: registry orchestration and guard support are missing.

- [ ] **Step 3: Add main-process registration**

Add `default_monitor_registry_file(country)` returning
`ROOT / "auto_repair_records" / f"{normalize_country(country)}_ds_failed_active_monitors.json"`.
Add `build_country_unhealthy_message(country, active_count, circuit_open_until, mentions)`
that renders the approved country, active-count, 30-minute circuit, and manual-action text.

After the per-instance `retry_lock`, construct the registry from environment configuration and call `register`. If circuit-open, skip `auto_retry`; only `alert_required=True` sends the country alert. Wrap accepted execution in `try/finally` and always unregister.

- [ ] **Step 4: Add a circuit guard to `auto_retry`**

Add an optional `monitor_guard: Callable[[], dict[str, Any]] | None = None` parameter to
`auto_retry` without changing existing required arguments.

Call the guard before each retry and before every polling `get_instance`. Circuit-open returns `status="country_circuit_open"`, makes no later DS call, and sends no instance-level final alert.

- [ ] **Step 5: Run retry tests and verify GREEN**

```bash
PYTHONPATH=. python3 -m unittest -v tests.ine_ds_failed_auto_retry_checks
```

- [ ] **Step 6: Commit Task 2**

```bash
git add tools/ds_failed_auto_retry.py tests/ine_ds_failed_auto_retry_checks.py
git commit -m "feat: add country DS retry circuit breaker"
```

### Task 3: Enforce the 30-minute lifecycle

**Files:**
- Modify: `tools/ds_failed_auto_retry.py`
- Modify: `tests/ine_ds_failed_auto_retry_checks.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_three_terminal_failures_notify_immediately_before_deadline(self):
    # Assert 3 retry calls and final alert with latest task reason, attempts, state.

def test_thirty_minute_deadline_stops_running_instance(self):
    # Assert timeout alert has task, reason, actual attempts, state and manual action.

def test_success_before_deadline_still_reports_recovery(self):
    # RUNNING -> SUCCESS; assert progress and recovery messages.
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Expected: current 24-hour count-based monitor does not meet the 1800-second deadline or timeout format.

- [ ] **Step 3: Replace count-based monitoring with a monotonic deadline**

```python
instance_timeout_seconds = max(1, int(os.getenv(
    "DS_FAILED_INSTANCE_TIMEOUT_SECONDS",
    os.getenv("DS_FAILED_MONITOR_TIMEOUT_SECONDS", "1800"),
)))
deadline = monotonic() + instance_timeout_seconds
```

Inject `monotonic: Callable[[], float] = time.monotonic` into `auto_retry`. Before every retry or poll, stop when the deadline is reached. Sleep for `min(monitor_interval_seconds, remaining_seconds)`. `UNKNOWN` keeps polling but cannot extend the deadline.

- [ ] **Step 4: Add terminal notification builders**

Add `build_three_failures_message(alert, attempts, state, reason, mentions, task_name)` and
`build_monitor_timeout_message(alert, attempts, state, reason, mentions, task_name)`.

Both include failed task, best task-level reason, attempts, state, and `需要负责人查看`. Attempt 3 terminal failure fires immediately; timeout fires for every non-success state at 30 minutes.

- [ ] **Step 5: Run retry tests and verify GREEN**

Run the Task 2 Step 5 command. Expected: all retry tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add tools/ds_failed_auto_retry.py tests/ine_ds_failed_auto_retry_checks.py
git commit -m "feat: bound DS auto retry to thirty minutes"
```

### Task 4: Full verification and push

**Files:**
- Verify all files above.

- [ ] **Step 1: Run all tests**

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -p '*checks.py'
```

Expected: zero failures and errors.

- [ ] **Step 2: Run compile and diff checks**

```bash
PYTHONPYCACHEPREFIX=/tmp/ds-monitor-circuit-pycache \
  python3 -m py_compile tools/ds_retry_monitor_registry.py tools/ds_failed_auto_retry.py \
  tests/ds_retry_monitor_registry_checks.py tests/ine_ds_failed_auto_retry_checks.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Verify spec coverage**

Confirm success, three failures, 30-minute timeout, threshold 10, single alert, all-monitor stop, 30-minute circuit recovery, stale cleanup, and country isolation are covered by tests.

- [ ] **Step 4: Push verified commits**

```bash
git fetch origin master
git rev-list --left-right --count HEAD...origin/master
git push origin master
```

Expected: no remote-only commits before push; remote `master` advances to the verified implementation.
