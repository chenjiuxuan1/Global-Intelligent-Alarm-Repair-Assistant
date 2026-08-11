import tempfile
import unittest
from pathlib import Path

from tools.ds_retry_monitor_registry import CountryMonitorRegistry


class FakeClock:
    def __init__(self, value: float = 1_000.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class CountryMonitorRegistryTests(unittest.TestCase):
    def make_registry(self, path: Path, clock: FakeClock) -> CountryMonitorRegistry:
        return CountryMonitorRegistry(
            path,
            active_limit=10,
            circuit_seconds=1800,
            stale_seconds=300,
            clock=clock,
            process_alive=lambda _: True,
        )

    def test_tenth_registration_opens_circuit_and_alerts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock()
            registry = self.make_registry(Path(tmp) / "pk.json", clock)

            for index in range(9):
                decision = registry.register(f"pk:p:{index}", pid=100 + index)
                self.assertTrue(decision["accepted"])
                self.assertFalse(decision["circuit_open"])

            tenth = registry.register("pk:p:9", pid=109)
            repeated = registry.heartbeat("pk:p:0", pid=100)

            self.assertFalse(tenth["accepted"])
            self.assertTrue(tenth["circuit_open"])
            self.assertTrue(tenth["alert_required"])
            self.assertEqual(tenth["active_count"], 10)
            self.assertEqual(tenth["circuit_open_until"], 2800.0)
            self.assertTrue(repeated["circuit_open"])
            self.assertFalse(repeated["alert_required"])

    def test_circuit_recovers_after_cooldown_when_active_count_is_below_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock()
            registry = self.make_registry(Path(tmp) / "pk.json", clock)
            keys = []
            for index in range(10):
                key = f"pk:p:{index}"
                keys.append(key)
                registry.register(key, pid=100 + index)
            for index, key in enumerate(keys):
                registry.unregister(key, pid=100 + index)

            blocked = registry.register("pk:blocked", pid=500)
            registry.unregister("pk:blocked", pid=500)
            clock.advance(1800)
            recovered = registry.register("pk:new", pid=999)

            self.assertFalse(blocked["accepted"])
            self.assertTrue(blocked["circuit_open"])
            self.assertTrue(recovered["accepted"])
            self.assertFalse(recovered["circuit_open"])
            self.assertFalse(recovered["alert_required"])

    def test_stale_heartbeat_is_removed_from_active_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock()
            registry = self.make_registry(Path(tmp) / "pk.json", clock)
            registry.register("pk:stale", pid=101)

            clock.advance(301)
            snapshot = registry.snapshot()

            self.assertEqual(snapshot["active_count"], 0)
            self.assertEqual(snapshot["monitors"], {})

    def test_dead_pid_is_removed_even_before_heartbeat_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock()
            registry = CountryMonitorRegistry(
                Path(tmp) / "pk.json",
                clock=clock,
                process_alive=lambda pid: pid != 101,
            )
            registry.register("pk:dead", pid=101)

            snapshot = registry.snapshot()

            self.assertEqual(snapshot["active_count"], 0)

    def test_country_files_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock()
            pk = self.make_registry(Path(tmp) / "pk.json", clock)
            ph = self.make_registry(Path(tmp) / "ph.json", clock)
            pk.register("pk:1", pid=101)

            self.assertEqual(pk.snapshot()["active_count"], 1)
            self.assertEqual(ph.snapshot()["active_count"], 0)


if __name__ == "__main__":
    unittest.main()
